"""Tests for the reference scope authoriser (spindl.auth.scopes).

``ScopeAuthoriser`` allows a tool when the identity holds every permission
the tool declares, and allows a tool that declares none for any
authenticated identity. It is composed into an authenticator, here a
product's own, and exercised both directly and through a real
``MCPServer`` over streamable HTTP.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
import pytest

from spindl.auth import AuthConfig, Authenticator, Credentials, Identity, ToolAction
from spindl.auth.scopes import Authoriser, ScopeAuthoriser
from spindl.server import MCPServer
from spindl.tool import BaseTool

RESOURCE_URL = "http://testserver/mcp"
AUTH_SERVER_URL = "https://auth.example.com"
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class ReadTool(BaseTool):
    name = "read_records"
    description = "Read records"
    category = "records"
    read_only = True
    permissions = ["records:read"]
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"read": True}


class ReviseTool(BaseTool):
    name = "revise_records"
    description = "Read and rewrite records"
    category = "records"
    destructive = True
    permissions = ["records:read", "records:write"]
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"revised": True}


class PingTool(BaseTool):
    name = "ping"
    description = "Declares no permissions"
    category = "general"
    read_only = True
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"pong": True}


def identity(*permissions: str) -> Identity:
    return Identity(subject="caller", tool_permissions=frozenset(permissions))


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


class TestScopeAuthoriser:
    @pytest.mark.parametrize("action", ["list", "call"])
    async def test_allows_a_tool_whose_permissions_are_all_held(self, action):
        authoriser = ScopeAuthoriser()
        caller = identity("records:read", "records:write", "other")
        assert await authoriser.authorise(caller, ReviseTool(), action) is True
        assert await authoriser.authorise(caller, ReadTool(), action) is True

    @pytest.mark.parametrize("action", ["list", "call"])
    async def test_refuses_a_tool_whose_permissions_are_only_partly_held(self, action):
        authoriser = ScopeAuthoriser()
        caller = identity("records:read")
        assert await authoriser.authorise(caller, ReviseTool(), action) is False

    async def test_refuses_a_tool_when_no_permission_is_held(self):
        authoriser = ScopeAuthoriser()
        assert await authoriser.authorise(identity(), ReadTool(), "call") is False
        assert await authoriser.authorise(identity("x"), ReadTool(), "list") is False

    @pytest.mark.parametrize("action", ["list", "call"])
    async def test_allows_a_tool_declaring_no_permissions_for_any_identity(
        self, action
    ):
        authoriser = ScopeAuthoriser()
        assert await authoriser.authorise(identity(), PingTool(), action) is True
        assert await authoriser.authorise(identity("x"), PingTool(), action) is True

    async def test_refuses_when_there_is_no_identity(self):
        authoriser = ScopeAuthoriser()
        assert await authoriser.authorise(None, PingTool(), "list") is False

    def test_is_an_authoriser(self):
        assert isinstance(ScopeAuthoriser(), Authoriser)


# ---------------------------------------------------------------------------
# Composed into a product's own authenticator, through a real server
# ---------------------------------------------------------------------------


class ProductAuthenticator:
    """A product's own authenticator, reusing ScopeAuthoriser for access."""

    def __init__(self, identities: dict[str, Identity]) -> None:
        self.identities = identities
        self.scopes = ScopeAuthoriser()

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        return self.identities.get(credentials.bearer_token or "")

    async def authorise(
        self, identity: Identity, tool: BaseTool, action: ToolAction
    ) -> bool:
        return await self.scopes.authorise(identity, tool, action)


@asynccontextmanager
async def product_client(
    authenticator: ProductAuthenticator, denial_mode: str = "hide"
) -> AsyncIterator[httpx.AsyncClient]:
    server = MCPServer(
        prefix="test",
        auth=AuthConfig(
            authenticator=authenticator,
            resource_server_url=RESOURCE_URL,
            authorization_servers=[AUTH_SERVER_URL],
            denial_mode=denial_mode,  # type: ignore[arg-type]
        ),
    )
    for tool in (ReadTool(), ReviseTool(), PingTool()):
        server.register(tool)
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def bearer(token: str) -> dict[str, str]:
    return {**JSON_HEADERS, "Authorization": f"Bearer {token}"}


class TestComposedIntoAProductAuthenticator:
    def make(self) -> ProductAuthenticator:
        # Synthetic opaque tokens for the product's own scheme.
        return ProductAuthenticator(
            {
                "reader-token": identity("records:read"),
                "editor-token": identity("records:read", "records:write"),
            }
        )

    def test_the_product_authenticator_is_an_authenticator(self):
        assert isinstance(self.make(), Authenticator)

    async def test_tools_list_is_filtered_by_held_permissions(self):
        async with product_client(self.make()) as client:
            reader = await client.post(
                "/mcp", json=rpc("tools/list"), headers=bearer("reader-token")
            )
            editor = await client.post(
                "/mcp", json=rpc("tools/list"), headers=bearer("editor-token")
            )
        reader_names = {t["name"] for t in reader.json()["result"]["tools"]}
        editor_names = {t["name"] for t in editor.json()["result"]["tools"]}
        assert {"test_read_records", "test_ping"} <= reader_names
        assert "test_revise_records" not in reader_names
        assert "test_revise_records" in editor_names

    async def test_a_call_lacking_a_permission_is_answered_as_an_unknown_tool(self):
        async with product_client(self.make()) as client:
            resp = await client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_revise_records"}),
                headers=bearer("reader-token"),
            )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload["error"]["error_code"] == "TOOL_NOT_FOUND"

    async def test_step_up_names_the_missing_permission(self):
        async with product_client(self.make(), denial_mode="step_up") as client:
            resp = await client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_revise_records"}),
                headers=bearer("reader-token"),
            )
        assert resp.status_code == 403
        assert 'scope="records:write"' in resp.headers["WWW-Authenticate"]

    async def test_a_tool_declaring_no_permissions_runs_for_any_caller(self):
        async with product_client(self.make()) as client:
            resp = await client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_ping"}),
                headers=bearer("reader-token"),
            )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        assert payload == {"pong": True}
