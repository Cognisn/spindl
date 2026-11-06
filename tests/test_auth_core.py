"""Tests for the 0.5.0 authentication core: Authenticator, Identity and reach.

Tool access (decided by ``Authenticator.authorise`` before any tool code
runs) and reach (what a permitted call may touch, enforced by the tool) are
separate controls; these tests pin both, the HTTP mechanics spindl owns, the
denial modes and the 0.4.0 adapters.
"""

import asyncio
import dataclasses
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
import pytest
import uvicorn
from mcp import Client
from mcp.client.sse import sse_client
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Route

from spindl.auth import (
    AccessTokenIdentity,
    AuthConfig,
    Authenticator,
    Credentials,
    Identity,
    ToolAction,
    ToolContext,
    current_identity,
    is_scope_token,
)
from spindl.server import MCPServer
from spindl.spooler.config import SpoolerConfig
from spindl.tool import BaseTool

RESOURCE_URL = "http://testserver/mcp"
AUTH_SERVER_URL = "http://auth.example"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
# The SSE tests need a real socket. Port 0 asks the OS for a free one; set
# SPINDL_TEST_PORT to keep the listener inside a reserved block.
TEST_PORT = int(os.environ.get("SPINDL_TEST_PORT", "0"))

ALICE = Identity(
    subject="alice",
    client_id="app",
    tool_permissions=frozenset({"read", "write"}),
    reach={"tenants": ["t1"]},
)
BOB = Identity(
    subject="bob",
    client_id="app",
    tool_permissions=frozenset({"read"}),
    reach={"tenants": ["t2"]},
)
CAROL = Identity(
    subject="carol",
    client_id="app",
    tool_permissions=frozenset({"read", "write"}),
    reach=None,
)
IDENTITIES = {"alice-key": ALICE, "bob-key": BOB, "carol-key": CAROL}

# Executions recorded by the test tools, so a test can prove no tool code ran.
EXECUTED: list[str] = []


class KeyAuthenticator:
    """Accepts fixed API keys from X-API-Key or a bearer token.

    Allows a tool when the identity holds every permission the tool
    declares, unless the (subject, tool) pair is in ``deny``.
    """

    def __init__(self, deny: set[tuple[str, str]] | None = None) -> None:
        self.deny = deny or set()
        self.credentials: list[Credentials] = []
        self.decisions: list[tuple[str, str, str]] = []
        self.identities = dict(IDENTITIES)

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        self.credentials.append(credentials)
        key = credentials.headers.get("x-api-key") or credentials.bearer_token
        return self.identities.get(key or "")

    async def authorise(
        self, identity: Identity, tool: BaseTool, action: ToolAction
    ) -> bool:
        self.decisions.append((identity.subject, tool.name, action))
        if (identity.subject, tool.name) in self.deny:
            return False
        return set(tool.permissions) <= identity.tool_permissions


class ReadTool(BaseTool):
    name = "read_records"
    description = "Read records the caller can reach"
    category = "records"
    read_only = True
    permissions = ["read"]

    class InputModel(BaseModel):
        limit: int = 10

    async def execute(self, **params: Any) -> dict[str, Any]:
        EXECUTED.append(self.name)
        context = self.context
        assert context is not None
        return {
            "subject": context.identity.subject if context.identity else None,
            "reach": context.reach,
            "prefix": context.instance_prefix,
        }


class WriteTool(BaseTool):
    name = "write_records"
    description = "Write records"
    category = "records"
    destructive = True
    permissions = ["write"]

    class InputModel(BaseModel):
        value: str = "x"

    async def execute(self, **params: Any) -> dict[str, Any]:
        EXECUTED.append(self.name)
        return {"written": True}


class PurgeTool(BaseTool):
    name = "purge"
    description = "Purge records"
    category = "records"
    destructive = True
    permissions = ["write", "admin", "audit"]

    async def execute(self, **params: Any) -> dict[str, Any]:
        EXECUTED.append(self.name)
        return {"purged": True}


class ReviseTool(BaseTool):
    name = "revise"
    description = "Read and rewrite records"
    category = "records"
    destructive = True
    permissions = ["read", "write"]

    async def execute(self, **params: Any) -> dict[str, Any]:
        EXECUTED.append(self.name)
        return {"revised": True}


class PingTool(BaseTool):
    name = "ping"
    description = "Touches nothing, so needs no reach"
    category = "general"
    read_only = True
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        EXECUTED.append(self.name)
        return {"pong": True}


class WhoAmITool(BaseTool):
    name = "whoami"
    description = "Return the caller"
    category = "general"
    read_only = True
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        identity = current_identity()
        return {
            "type": type(identity).__name__,
            "subject": identity.subject if identity else None,
            "same": identity is (self.context.identity if self.context else None),
        }


class SpoolingTool(BaseTool):
    name = "big_list"
    description = "Returns enough rows to be spooled"
    category = "records"
    read_only = True
    spooler_auto_detect = True

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {"rows": [{"n": n} for n in range(40)]}}


def make_auth(
    authenticator: Any = None,
    *,
    denial_mode: str = "hide",
    required_scopes: list[str] | None = None,
    scopes_supported: list[str] | None = None,
) -> AuthConfig:
    return AuthConfig(
        authenticator=authenticator or KeyAuthenticator(),
        resource_server_url=RESOURCE_URL,
        authorization_servers=[AUTH_SERVER_URL],
        credential_headers=["X-API-Key"],
        required_scopes=required_scopes or [],
        scopes_supported=scopes_supported,
        denial_mode=denial_mode,  # type: ignore[arg-type]
    )


def make_server(
    auth: AuthConfig | None = None, *, spooler: bool = False, tools: Any = None
) -> MCPServer:
    server = MCPServer(
        prefix="test",
        auth=auth,
        spooler=SpoolerConfig(db_path=":memory:") if spooler else None,
    )
    for tool in tools or [ReadTool(), WriteTool(), PurgeTool(), PingTool()]:
        server.register(tool)
    server.register(WhoAmITool())
    return server


async def build_with_http_app(server: MCPServer) -> Starlette:
    app: Starlette = await server.build_http_app()
    return app


async def build_with_http_endpoint(server: MCPServer) -> Starlette:
    endpoint = await server.http_endpoint()
    routes: list[Any] = list(server._metadata_routes())
    routes.append(Route("/mcp", endpoint, methods=["POST", "GET", "DELETE"]))
    return Starlette(routes=routes, lifespan=server.http_lifespan)


HTTP_BUILDERS = pytest.mark.parametrize(
    "build",
    [build_with_http_app, build_with_http_endpoint],
    ids=["build_http_app", "http_endpoint"],
)

AppBuilder = Callable[[MCPServer], Awaitable[Starlette]]


@asynccontextmanager
async def client_for(
    server: MCPServer, build: AppBuilder = build_with_http_app
) -> AsyncIterator[httpx.AsyncClient]:
    app = await build(server)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def key_headers(key: str | None, **extra: str) -> dict[str, str]:
    headers = {**JSON_HEADERS, **extra}
    if key is not None:
        headers["X-API-Key"] = key
    return headers


async def list_names(client: httpx.AsyncClient, key: str) -> set[str]:
    resp = await client.post("/mcp", json=rpc("tools/list"), headers=key_headers(key))
    assert resp.status_code == 200, resp.text
    return {tool["name"] for tool in resp.json()["result"]["tools"]}


async def call_raw(
    client: httpx.AsyncClient,
    key: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    **headers: str,
) -> httpx.Response:
    return await client.post(
        "/mcp",
        json=rpc("tools/call", {"name": name, "arguments": arguments or {}}),
        headers=key_headers(key, **headers),
    )


async def call_tool(
    client: httpx.AsyncClient,
    key: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    **headers: str,
) -> Any:
    resp = await call_raw(client, key, name, arguments, **headers)
    assert resp.status_code == 200, resp.text
    return json.loads(resp.json()["result"]["content"][0]["text"])


@pytest.fixture(autouse=True)
def clear_executions() -> None:
    EXECUTED.clear()


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class TestTypes:
    def test_credentials_are_frozen_with_a_read_only_lower_cased_header_mapping(self):
        creds = Credentials(bearer_token="tok", headers={"X-API-Key": "k"})
        assert dict(creds.headers) == {"x-api-key": "k"}
        with pytest.raises(TypeError):
            creds.headers["x-api-key"] = "other"  # type: ignore[index]
        with pytest.raises(dataclasses.FrozenInstanceError):
            creds.bearer_token = "other"  # type: ignore[misc]

    def test_credentials_repr_shows_no_secret(self):
        creds = Credentials(bearer_token="s3cret-token", headers={"x-api-key": "k3y"})
        assert "s3cret-token" not in repr(creds)
        assert "k3y" not in repr(creds)

    def test_identity_is_frozen_and_requires_a_subject(self):
        with pytest.raises(ValueError):
            Identity(subject="")
        identity = Identity(subject="s", tool_permissions={"a", "b"})  # type: ignore[arg-type]
        assert identity.tool_permissions == frozenset({"a", "b"})
        assert identity.client_id is None and identity.reach is None
        assert identity.expires_at is None
        with pytest.raises(dataclasses.FrozenInstanceError):
            identity.reach = {"all": True}  # type: ignore[misc]

    def test_tool_context_is_frozen(self):
        context = ToolContext(identity=ALICE, reach=ALICE.reach, instance_prefix=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            context.reach = None  # type: ignore[misc]

    def test_authenticator_protocol_is_checkable(self):
        assert isinstance(KeyAuthenticator(), Authenticator)
        assert not isinstance(object(), Authenticator)

    @pytest.mark.parametrize("name", ["read", "files:read", "a.b/c-d_e", "~!#[]"])
    def test_valid_scope_tokens(self, name):
        assert is_scope_token(name)

    @pytest.mark.parametrize("name", ["", "two words", 'quo"te', "back\\slash", "é"])
    def test_invalid_scope_tokens(self, name):
        assert not is_scope_token(name)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestAuthConfig:
    def test_authenticator_config_defaults(self, caplog):
        caplog.set_level(logging.WARNING)
        cfg = make_auth()
        assert cfg.denial_mode == "hide"
        assert cfg.credential_headers == ["x-api-key"]
        assert not [r for r in caplog.records if "deprecated" in r.getMessage()]

    def test_neither_authenticator_nor_verifier_is_refused(self):
        with pytest.raises(ValueError):
            AuthConfig(
                resource_server_url=RESOURCE_URL,
                authorization_servers=[AUTH_SERVER_URL],
            )

    def test_authenticator_with_token_verifier_is_refused(self):
        with pytest.raises(ValueError, match="not both"):
            AuthConfig(
                token_verifier=LegacyVerifier(),
                authenticator=KeyAuthenticator(),
                resource_server_url=RESOURCE_URL,
                authorization_servers=[AUTH_SERVER_URL],
            )

    def test_authenticator_with_tool_visibility_is_refused(self):
        with pytest.raises(ValueError, match="tool_visibility"):
            MCPServer(
                prefix="test", auth=make_auth(), tool_visibility=lambda i, t: True
            )

    def test_object_that_is_not_an_authenticator_is_refused(self):
        with pytest.raises(TypeError):
            AuthConfig(
                authenticator=object(),  # type: ignore[arg-type]
                resource_server_url=RESOURCE_URL,
                authorization_servers=[AUTH_SERVER_URL],
            )

    def test_unknown_denial_mode_is_refused(self):
        with pytest.raises(ValueError, match="denial_mode"):
            make_auth(denial_mode="silent")

    def test_authorization_is_not_a_credential_header(self):
        with pytest.raises(ValueError):
            AuthConfig(
                authenticator=KeyAuthenticator(),
                resource_server_url=RESOURCE_URL,
                authorization_servers=[AUTH_SERVER_URL],
                credential_headers=["Authorization"],
            )

    def test_token_verifier_logs_one_deprecation_warning(self, caplog):
        caplog.set_level(logging.WARNING)
        AuthConfig(
            token_verifier=LegacyVerifier(),
            resource_server_url=RESOURCE_URL,
            authorization_servers=[AUTH_SERVER_URL],
        )
        warnings = [r for r in caplog.records if "token_verifier" in r.getMessage()]
        assert len(warnings) == 1
        assert "deprecated" in warnings[0].getMessage()

    def test_tool_visibility_logs_one_deprecation_warning(self, caplog):
        caplog.set_level(logging.WARNING)
        MCPServer(prefix="test", tool_visibility=lambda identity, tool: True)
        warnings = [r for r in caplog.records if "tool_visibility" in r.getMessage()]
        assert len(warnings) == 1
        assert "deprecated" in warnings[0].getMessage()

    def test_positional_0_4_0_construction_still_works(self):
        cfg = AuthConfig(LegacyVerifier(), RESOURCE_URL, [AUTH_SERVER_URL], ["read"])
        assert cfg.required_scopes == ["read"]
        assert cfg.scopes_supported == ["read"]


# ---------------------------------------------------------------------------
# HTTP mechanics spindl owns
# ---------------------------------------------------------------------------


class TestMechanics:
    @HTTP_BUILDERS
    async def test_no_credential_gets_401_with_the_metadata_challenge(self, build):
        authenticator = KeyAuthenticator()
        server = make_server(make_auth(authenticator))
        async with client_for(server, build) as client:
            resp = await client.post(
                "/mcp", json=rpc("tools/list"), headers=JSON_HEADERS
            )
        assert resp.status_code == 401
        challenge = resp.headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        assert f'resource_metadata="http://testserver{METADATA_PATH}"' in challenge
        assert authenticator.credentials == []

    @HTTP_BUILDERS
    async def test_unaccepted_credential_gets_401(self, build):
        server = make_server(make_auth())
        async with client_for(server, build) as client:
            resp = await client.post(
                "/mcp", json=rpc("tools/list"), headers=key_headers("wrong-key")
            )
        assert resp.status_code == 401
        assert 'error="invalid_token"' in resp.headers["www-authenticate"]
        assert "resource_metadata=" in resp.headers["www-authenticate"]

    async def test_a_raising_authenticator_gets_401_and_logs_no_credential(
        self, caplog
    ):
        class Broken(KeyAuthenticator):
            async def authenticate(self, credentials):
                raise RuntimeError(f"bad key {credentials.headers['x-api-key']}")

        caplog.set_level(logging.DEBUG)
        server = make_server(make_auth(Broken()))
        async with client_for(server) as client:
            resp = await client.post(
                "/mcp", json=rpc("tools/list"), headers=key_headers("very-secret-key")
            )
        assert resp.status_code == 401
        logged = caplog.text + "".join(
            str(r.exc_info) for r in caplog.records if r.exc_info
        )
        assert "very-secret-key" not in logged

    async def test_expired_identity_gets_401(self):
        authenticator = KeyAuthenticator()
        authenticator.identities["old-key"] = Identity(
            subject="old", reach={}, expires_at=time.time() - 60
        )
        server = make_server(make_auth(authenticator))
        async with client_for(server) as client:
            resp = await client.post(
                "/mcp", json=rpc("tools/list"), headers=key_headers("old-key")
            )
        assert resp.status_code == 401

    @HTTP_BUILDERS
    async def test_configured_header_and_bearer_token_reach_the_authenticator(
        self, build
    ):
        authenticator = KeyAuthenticator()
        server = make_server(make_auth(authenticator))
        async with client_for(server, build) as client:
            by_header = await client.post(
                "/mcp",
                json=rpc("tools/list"),
                headers={**JSON_HEADERS, "X-API-KEY": "alice-key", "X-Other": "no"},
            )
            by_bearer = await client.post(
                "/mcp",
                json=rpc("tools/list"),
                headers={**JSON_HEADERS, "Authorization": "Bearer bob-key"},
            )
        assert by_header.status_code == 200
        assert by_bearer.status_code == 200
        first, second = authenticator.credentials
        assert dict(first.headers) == {"x-api-key": "alice-key"}
        assert first.bearer_token is None
        assert second.bearer_token == "bob-key"
        assert dict(second.headers) == {}

    @HTTP_BUILDERS
    async def test_required_scopes_are_checked_against_tool_permissions(self, build):
        server = make_server(make_auth(required_scopes=["write"]))
        async with client_for(server, build) as client:
            bob = await client.post(
                "/mcp", json=rpc("tools/list"), headers=key_headers("bob-key")
            )
            alice = await client.post(
                "/mcp", json=rpc("tools/list"), headers=key_headers("alice-key")
            )
        assert bob.status_code == 403
        assert 'error="insufficient_scope"' in bob.headers["www-authenticate"]
        assert alice.status_code == 200

    async def test_current_identity_returns_the_identity(self):
        server = make_server(make_auth())
        async with client_for(server) as client:
            payload = await call_tool(client, "alice-key", "test_whoami")
        assert payload == {"type": "Identity", "subject": "alice", "same": True}


class TestMetadata:
    @HTTP_BUILDERS
    async def test_scopes_supported_is_the_union_of_configured_and_tool_scopes(
        self, build
    ):
        server = make_server(make_auth(scopes_supported=["read", "profile", "zeta"]))
        async with client_for(server, build) as client:
            resp = await client.get(METADATA_PATH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["scopes_supported"] == [
            "admin",
            "audit",
            "profile",
            "read",
            "write",
            "zeta",
        ]
        assert body["resource"] == RESOURCE_URL
        assert body["authorization_servers"] == [AUTH_SERVER_URL]

    async def test_required_scopes_are_advertised_when_nothing_else_is(self):
        server = make_server(make_auth(required_scopes=["read"]), tools=[PingTool()])
        async with client_for(server) as client:
            body = (await client.get(METADATA_PATH)).json()
        assert body["scopes_supported"] == ["read"]


# ---------------------------------------------------------------------------
# Tool access
# ---------------------------------------------------------------------------


class TestToolAccessHide:
    @HTTP_BUILDERS
    async def test_authorise_list_filters_tools_list(self, build):
        authenticator = KeyAuthenticator()
        server = make_server(make_auth(authenticator))
        async with client_for(server, build) as client:
            bob = await list_names(client, "bob-key")
            alice = await list_names(client, "alice-key")
        assert "test_write_records" not in bob and "test_purge" not in bob
        assert "test_read_records" in bob
        assert "test_write_records" in alice
        assert ("bob", "write_records", "list") in authenticator.decisions

    @HTTP_BUILDERS
    async def test_denied_call_is_answered_exactly_as_an_unknown_tool(self, build):
        denied_server = make_server(make_auth())
        absent_server = make_server(make_auth(), tools=[ReadTool(), PingTool()])
        async with client_for(denied_server, build) as client:
            denied = await call_raw(client, "bob-key", "test_write_records")
        async with client_for(absent_server, build) as client:
            absent = await call_raw(client, "bob-key", "test_write_records")
        assert denied.status_code == absent.status_code == 200
        assert denied.json() == absent.json()
        text = json.loads(denied.json()["result"]["content"][0]["text"])
        assert text["error"]["error_code"] == "TOOL_NOT_FOUND"
        assert EXECUTED == []

    async def test_authorise_call_runs_before_argument_validation(self):
        authenticator = KeyAuthenticator()
        server = make_server(make_auth(authenticator))
        async with client_for(server) as client:
            payload = await call_tool(
                client, "bob-key", "test_write_records", {"unexpected": 1}
            )
        assert payload["error"]["error_code"] == "TOOL_NOT_FOUND"
        assert ("bob", "write_records", "call") in authenticator.decisions
        assert EXECUTED == []

    async def test_allowed_call_runs(self):
        server = make_server(make_auth())
        async with client_for(server) as client:
            payload = await call_tool(client, "alice-key", "test_write_records")
        assert payload == {"written": True}

    async def test_skills_tools_honour_the_decision(self):
        server = make_server(make_auth())
        async with client_for(server) as client:
            listed = await call_tool(client, "bob-key", "test_list_tools")
            described = await call_tool(
                client, "bob-key", "test_describe_tool", {"tool_name": "test_purge"}
            )
            allowed = await call_tool(
                client,
                "alice-key",
                "test_describe_tool",
                {"tool_name": "test_write_records"},
            )
        names = {
            t["name"] for group in listed["data"]["categories"].values() for t in group
        }
        assert "test_purge" not in names and "test_read_records" in names
        assert listed["data"]["total_tools"] == len(names)
        assert described["error"]["error_code"] == "TOOL_NOT_FOUND"
        assert allowed["success"] is True

    async def test_a_raising_authorise_denies_the_tool(self, caplog):
        class Flaky(KeyAuthenticator):
            async def authorise(self, identity, tool, action):
                if tool.name == "read_records":
                    raise RuntimeError("policy store down")
                return True

        caplog.set_level(logging.WARNING)
        server = make_server(make_auth(Flaky()))
        async with client_for(server) as client:
            names = await list_names(client, "alice-key")
            payload = await call_tool(client, "alice-key", "test_read_records")
        assert "test_read_records" not in names
        assert payload["error"]["error_code"] == "TOOL_NOT_FOUND"
        assert EXECUTED == []


class TestStepUp:
    @HTTP_BUILDERS
    async def test_tool_lacking_permissions_stays_listed(self, build):
        server = make_server(make_auth(denial_mode="step_up"))
        async with client_for(server, build) as client:
            names = await list_names(client, "bob-key")
        assert {"test_write_records", "test_purge", "test_read_records"} <= names

    @HTTP_BUILDERS
    async def test_call_answers_403_insufficient_scope_naming_missing_permissions(
        self, build
    ):
        server = make_server(make_auth(denial_mode="step_up"))
        async with client_for(server, build) as client:
            one = await call_raw(client, "bob-key", "test_write_records")
            several = await call_raw(client, "bob-key", "test_purge")
        assert one.status_code == 403
        challenge = one.headers["www-authenticate"]
        assert 'error="insufficient_scope"' in challenge
        assert 'scope="write"' in challenge
        assert f'resource_metadata="http://testserver{METADATA_PATH}"' in challenge
        assert several.status_code == 403
        assert 'scope="admin audit write"' in several.headers["www-authenticate"]
        assert EXECUTED == []

    async def test_the_challenge_names_only_the_permissions_lacking(self):
        server = make_server(
            make_auth(denial_mode="step_up"), tools=[ReviseTool(), PingTool()]
        )
        async with client_for(server) as client:
            resp = await call_raw(client, "bob-key", "test_revise")
        assert resp.status_code == 403
        challenge = resp.headers["www-authenticate"]
        assert 'scope="write"' in challenge
        assert "read" not in challenge.split('scope="')[1].split('"')[0]
        assert resp.json()["scope"] == "write"
        assert EXECUTED == []

    async def test_a_denial_for_another_reason_is_answered_as_unknown(self):
        authenticator = KeyAuthenticator(deny={("alice", "read_records")})
        server = make_server(make_auth(authenticator, denial_mode="step_up"))
        absent_server = make_server(
            make_auth(denial_mode="step_up"), tools=[WriteTool(), PingTool()]
        )
        async with client_for(server) as client:
            names = await list_names(client, "alice-key")
            denied = await call_raw(client, "alice-key", "test_read_records")
        async with client_for(absent_server) as client:
            absent = await call_raw(client, "alice-key", "test_read_records")
        assert "test_read_records" not in names
        assert denied.status_code == 200
        assert denied.json() == absent.json()
        assert EXECUTED == []

    async def test_hide_mode_hides_a_tool_lacking_permissions(self):
        server = make_server(make_auth(denial_mode="hide"))
        async with client_for(server) as client:
            names = await list_names(client, "bob-key")
            resp = await call_raw(client, "bob-key", "test_write_records")
        assert "test_write_records" not in names
        assert resp.status_code == 200
        text = json.loads(resp.json()["result"]["content"][0]["text"])
        assert text["error"]["error_code"] == "TOOL_NOT_FOUND"

    async def test_step_up_holds_inside_the_tool_handler_as_well(self):
        # In-memory: no HTTP layer, so the handler itself must refuse.
        from spindl.auth._context import reset_identity, set_identity

        server = make_server(make_auth(denial_mode="step_up"))
        await server._setup()
        token = set_identity(BOB)
        try:
            content = await server._handle_call_tool("test_write_records", {})
        finally:
            reset_identity(token)
        payload = json.loads(content[0].text)
        assert payload["error"]["error_code"] == "INSUFFICIENT_SCOPE"
        assert "write" in payload["error"]["error_message"]
        assert EXECUTED == []


# ---------------------------------------------------------------------------
# Declared permissions
# ---------------------------------------------------------------------------


class TestPermissionsDeclaration:
    def test_defaults(self):
        assert BaseTool.permissions == []
        assert BaseTool.requires_reach is None

    @pytest.mark.parametrize(
        "permissions", [["two words"], ['quo"te'], ["back\\slash"], [""], "read"]
    )
    def test_registration_refuses_invalid_permission_names(self, permissions):
        class Bad(BaseTool):
            name = "bad"
            description = "bad"
            read_only = True

        Bad.permissions = permissions
        with pytest.raises(ValueError, match="permission"):
            MCPServer(prefix="test").register(Bad())

    def test_registration_accepts_scope_tokens(self):
        MCPServer(prefix="test").register(PurgeTool())


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


class TestReach:
    async def test_a_call_without_reach_is_refused_before_tool_code_runs(self):
        server = make_server(make_auth())
        async with client_for(server) as client:
            payload = await call_tool(client, "carol-key", "test_read_records")
        error = payload["error"]
        assert error["error_code"] == "REACH_REQUIRED"
        assert "reach" in error["error_message"]
        assert "access" in error["error_message"]
        assert error["retry_eligible"] is False
        assert EXECUTED == []

    async def test_requires_reach_false_opts_out(self):
        server = make_server(make_auth())
        async with client_for(server) as client:
            payload = await call_tool(client, "carol-key", "test_ping")
        assert payload == {"pong": True}

    async def test_built_in_tools_need_no_reach(self):
        server = make_server(make_auth(), spooler=True)
        async with client_for(server) as client:
            listed = await call_tool(client, "carol-key", "test_list_tools")
            described = await call_tool(
                client, "carol-key", "test_describe_tool", {"tool_name": "test_ping"}
            )
            spools = await call_tool(client, "carol-key", "test_spooler_list")
        assert listed["success"] is True
        assert described["success"] is True
        assert "error" not in spools

    def test_built_in_tool_classes_declare_requires_reach_false(self):
        from spindl.skills.describe_tool import DescribeToolTool
        from spindl.skills.list_tools import ListToolsTool
        from spindl.spooler.tools.aggregate import SpoolerAggregateTool
        from spindl.spooler.tools.distinct import SpoolerDistinctTool
        from spindl.spooler.tools.list_spools import SpoolerListSpoolsTool
        from spindl.spooler.tools.query import SpoolerQueryTool

        for cls in (
            ListToolsTool,
            DescribeToolTool,
            SpoolerListSpoolsTool,
            SpoolerQueryTool,
            SpoolerAggregateTool,
            SpoolerDistinctTool,
        ):
            assert cls.requires_reach is False, cls.__name__

    async def test_reach_is_handed_to_the_tool(self):
        server = make_server(make_auth())
        async with client_for(server) as client:
            alice = await call_tool(client, "alice-key", "test_read_records")
            bob = await call_tool(client, "bob-key", "test_read_records")
        assert alice == {
            "subject": "alice",
            "reach": {"tenants": ["t1"]},
            "prefix": None,
        }
        assert bob["reach"] == {"tenants": ["t2"]}

    async def test_the_0_4_0_adapter_does_not_require_reach(self):
        server = make_server(legacy_auth())
        async with client_for(server) as client:
            resp = await client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_read_records", "arguments": {}}),
                headers={**JSON_HEADERS, "Authorization": "Bearer good-token"},
            )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload == {"subject": "user-1", "reach": None, "prefix": None}

    async def test_no_authentication_does_not_require_reach(self):
        server = make_server()
        async with client_for(server) as client:
            payload = await call_tool(client, None, "test_read_records")  # type: ignore[arg-type]
        assert payload == {"subject": None, "reach": None, "prefix": None}


# ---------------------------------------------------------------------------
# Spooler confinement
# ---------------------------------------------------------------------------


class TestSpoolerConfinement:
    async def test_spools_are_confined_to_the_identity_subject(self):
        server = make_server(make_auth(), spooler=True, tools=[SpoolingTool()])
        async with client_for(server) as client:
            created = await call_tool(client, "alice-key", "test_big_list")
            spool_id = created["data"]["spooled_data"][0]["spool_id"]
            alice = await call_tool(client, "alice-key", "test_spooler_list")
            bob = await call_tool(client, "bob-key", "test_spooler_list")
            bob_query = await call_tool(
                client, "bob-key", "test_spooler_query", {"spool_id": spool_id}
            )
        assert spool_id in json.dumps(alice)
        assert spool_id not in json.dumps(bob)
        assert "error" in bob_query
        assert server._spooler is not None


# ---------------------------------------------------------------------------
# 0.4.0 adapters
# ---------------------------------------------------------------------------


class LegacyVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token == "good-token":
            return AccessToken(
                token="good-token",
                client_id="client-a",
                scopes=["read", "write"],
                subject="user-1",
            )
        if token == "nosub-token":
            return AccessToken(token="nosub-token", client_id="client-b", scopes=[])
        return None


def legacy_auth() -> AuthConfig:
    return AuthConfig(
        token_verifier=LegacyVerifier(),
        resource_server_url=RESOURCE_URL,
        authorization_servers=[AUTH_SERVER_URL],
    )


class LegacyTool(BaseTool):
    name = "legacy"
    description = "Reads identity the 0.4.0 way"
    category = "general"

    async def execute(self, **params: Any) -> dict[str, Any]:
        from mcp.server.auth.middleware.auth_context import get_access_token

        identity: Any = current_identity()
        sdk = get_access_token()
        return {
            "subject": identity.subject,
            "client_id": identity.client_id,
            "scopes": identity.scopes,
            "permissions": sorted(identity.tool_permissions),
            "is_identity": isinstance(identity, Identity),
            "sdk_subject": sdk.subject if sdk else None,
        }


class TestLegacyAdapters:
    async def test_token_verifier_identity_keeps_the_0_4_0_attributes(self):
        server = make_server(legacy_auth(), tools=[LegacyTool()])
        async with client_for(server) as client:
            resp = await client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_legacy", "arguments": {}}),
                headers={**JSON_HEADERS, "Authorization": "Bearer good-token"},
            )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload == {
            "subject": "user-1",
            "client_id": "client-a",
            "scopes": ["read", "write"],
            "permissions": ["read", "write"],
            "is_identity": True,
            "sdk_subject": "user-1",
        }

    async def test_visibility_hook_receives_the_access_token(self):
        seen: list[Any] = []

        def hook(identity: Any, tool: BaseTool) -> bool:
            seen.append(identity)
            return tool.name != "write_records"

        server = MCPServer(prefix="test", auth=legacy_auth(), tool_visibility=hook)
        server.register(ReadTool())
        server.register(WriteTool())
        async with client_for(server) as client:
            resp = await client.post(
                "/mcp",
                json=rpc("tools/list"),
                headers={**JSON_HEADERS, "Authorization": "Bearer good-token"},
            )
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert "test_write_records" not in names
        assert seen and all(type(i) is AccessToken for i in seen)
        assert seen[0].token == "good-token"

    def test_adapter_identity_takes_permissions_from_scopes_and_no_reach(self):
        from spindl.auth import TokenVerifierAuthenticator

        adapter = TokenVerifierAuthenticator(LegacyVerifier())
        identity = asyncio.run(
            adapter.authenticate(Credentials(bearer_token="good-token"))
        )
        assert isinstance(identity, AccessTokenIdentity)
        assert identity.subject == "user-1"
        assert identity.tool_permissions == frozenset({"read", "write"})
        assert identity.reach is None
        no_subject = asyncio.run(
            adapter.authenticate(Credentials(bearer_token="nosub-token"))
        )
        assert no_subject is not None and no_subject.subject == "client-b"
        assert "good-token" not in repr(identity)


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------


@asynccontextmanager
async def running_sse_server(server: MCPServer) -> AsyncIterator[str]:
    app = await server.build_sse_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="warning")
    uv_server = uvicorn.Server(config)
    task = asyncio.create_task(uv_server.serve())
    try:
        while not uv_server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.02)
        port = uv_server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        uv_server.should_exit = True
        await task


class TestSse:
    async def test_no_credential_gets_401_on_both_endpoints(self):
        server = make_server(make_auth())
        app = await server.build_sse_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            sse = await client.get("/sse")
            messages = await client.post("/messages/?session_id=abc", json={})
        assert sse.status_code == messages.status_code == 401
        assert "resource_metadata=" in sse.headers["www-authenticate"]

    async def test_step_up_answers_403_on_the_messages_post(self):
        server = make_server(make_auth(denial_mode="step_up"))
        app = await server.build_sse_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/messages/?session_id=0123456789abcdef0123456789abcdef",
                json=rpc("tools/call", {"name": "test_write_records", "arguments": {}}),
                headers=key_headers("bob-key"),
            )
        assert resp.status_code == 403
        assert 'scope="write"' in resp.headers["www-authenticate"]

    async def test_access_and_reach_through_an_sse_session(self):
        server = make_server(make_auth(), spooler=False)
        async with running_sse_server(server) as base:
            async with Client(
                sse_client(f"{base}/sse", headers={"X-API-Key": "bob-key"}), cache=None
            ) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                read = await client.call_tool("test_read_records", {})
            async with Client(
                sse_client(f"{base}/sse", headers={"X-API-Key": "carol-key"}),
                cache=None,
            ) as client:
                refused = await client.call_tool("test_read_records", {})
        assert "test_write_records" not in names and "test_read_records" in names
        assert json.loads(read.content[0].text)["reach"] == {"tenants": ["t2"]}
        error = json.loads(refused.content[0].text)["error"]
        assert error["error_code"] == "REACH_REQUIRED"
