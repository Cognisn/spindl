"""Tests for resource-server authentication on the HTTP and SSE transports."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel

from spindl.auth import AuthConfig, current_identity
from spindl.server import MCPServer
from spindl.tool import BaseTool

RESOURCE_URL = "http://testserver/mcp"
AUTH_SERVER_URL = "http://auth.example/"


class StaticVerifier:
    """Token verifier that accepts a fixed set of tokens."""

    def __init__(self) -> None:
        self.tokens = {
            "good-token": AccessToken(
                token="good-token",
                client_id="client-a",
                scopes=["read", "write"],
                subject="user-1",
            ),
            "weak-token": AccessToken(
                token="weak-token",
                client_id="client-b",
                scopes=["read"],
                subject="user-2",
            ),
        }

    async def verify_token(self, token: str) -> AccessToken | None:
        return self.tokens.get(token)


class WhoAmITool(BaseTool):
    name = "whoami"
    description = "Return the authenticated caller"
    category = "diagnostics"

    class InputModel(BaseModel):
        pass

    def guide(self) -> str:
        return "Call @whoami."

    async def execute(self, **params) -> dict:
        identity = current_identity()
        return {
            "subject": identity.subject if identity else None,
            "scopes": identity.scopes if identity else [],
        }


def make_auth(required_scopes=None) -> AuthConfig:
    return AuthConfig(
        token_verifier=StaticVerifier(),
        resource_server_url=RESOURCE_URL,
        authorization_servers=[AUTH_SERVER_URL],
        required_scopes=required_scopes if required_scopes is not None else ["read"],
    )


@asynccontextmanager
async def running_app(app):
    """Run the Starlette lifespan and yield an httpx client bound to the app."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client, transport


INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class TestHttpAuth:
    async def test_missing_token_gets_401_with_resource_metadata_challenge(self):
        server = MCPServer(prefix="test", auth=make_auth())
        app = await server.build_http_app()
        async with running_app(app) as (client, _):
            resp = await client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
        assert resp.status_code == 401
        challenge = resp.headers["www-authenticate"]
        assert challenge.startswith("Bearer")
        assert "/.well-known/oauth-protected-resource" in challenge

    async def test_protected_resource_metadata_is_served(self):
        server = MCPServer(prefix="test", auth=make_auth())
        app = await server.build_http_app()
        async with running_app(app) as (client, _):
            resp = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert resp.status_code == 200
        body = resp.json()
        assert body["resource"] == RESOURCE_URL
        assert body["authorization_servers"] == [AUTH_SERVER_URL]

    async def test_token_lacking_required_scope_gets_403(self):
        server = MCPServer(prefix="test", auth=make_auth(["write"]))
        app = await server.build_http_app()
        async with running_app(app) as (client, _):
            resp = await client.post(
                "/mcp",
                json=INIT_BODY,
                headers={**MCP_HEADERS, "Authorization": "Bearer weak-token"},
            )
        assert resp.status_code == 403

    async def test_invalid_token_gets_401(self):
        server = MCPServer(prefix="test", auth=make_auth())
        app = await server.build_http_app()
        async with running_app(app) as (client, _):
            resp = await client.post(
                "/mcp",
                json=INIT_BODY,
                headers={**MCP_HEADERS, "Authorization": "Bearer bogus"},
            )
        assert resp.status_code == 401

    async def test_authenticated_tool_call_sees_caller_identity(self):
        server = MCPServer(prefix="test", auth=make_auth())
        server.register(WhoAmITool())
        app = await server.build_http_app()
        async with running_app(app) as (_, transport):
            http_client = httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": "Bearer good-token"},
            )
            async with streamable_http_client(
                RESOURCE_URL, http_client=http_client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("test_whoami", {})
        payload = json.loads(result.content[0].text)
        assert payload["subject"] == "user-1"
        assert payload["scopes"] == ["read", "write"]

    async def test_no_auth_config_leaves_endpoint_open(self):
        server = MCPServer(prefix="test")
        app = await server.build_http_app()
        async with running_app(app) as (client, _):
            resp = await client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
            metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert resp.status_code == 200
        assert metadata.status_code == 404


class TestSseAuth:
    async def test_missing_token_gets_401_on_sse(self):
        server = MCPServer(prefix="test", auth=make_auth())
        app = await server.build_sse_app()
        async with running_app(app) as (client, _):
            resp = await client.get("/sse")
        assert resp.status_code == 401
        assert (
            "/.well-known/oauth-protected-resource" in resp.headers["www-authenticate"]
        )

    async def test_missing_token_gets_401_on_messages(self):
        server = MCPServer(prefix="test", auth=make_auth())
        app = await server.build_sse_app()
        async with running_app(app) as (client, _):
            resp = await client.post("/messages/?session_id=abc", json={})
        assert resp.status_code == 401


class TestIdentityAccessor:
    def test_current_identity_is_none_outside_a_request(self):
        assert current_identity() is None


class TestAuthConfig:
    def test_required_scopes_default_to_empty(self):
        cfg = AuthConfig(
            token_verifier=StaticVerifier(),
            resource_server_url=RESOURCE_URL,
            authorization_servers=[AUTH_SERVER_URL],
        )
        assert cfg.required_scopes == []

    def test_requires_at_least_one_authorization_server(self):
        with pytest.raises(ValueError):
            AuthConfig(
                token_verifier=StaticVerifier(),
                resource_server_url=RESOURCE_URL,
                authorization_servers=[],
            )


class TestMountableTransports:
    async def test_http_path_is_configurable(self):
        server = MCPServer(prefix="test")
        app = await server.build_http_app(path="/")
        async with running_app(app) as (client, _):
            at_root = await client.post("/", json=INIT_BODY, headers=MCP_HEADERS)
            at_mcp = await client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
        assert at_root.status_code == 200
        assert at_mcp.status_code == 404

    async def test_http_endpoint_mounts_exactly_on_gateway_route(self):
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        server = MCPServer(prefix="test", auth=make_auth())
        server.register(WhoAmITool())
        endpoint = await server.http_endpoint()

        async def other(request):
            return PlainTextResponse("gateway")

        gateway = Starlette(
            routes=[
                Route("/other", other),
                Route("/mcp", endpoint, methods=["POST", "GET", "DELETE"]),
            ],
            lifespan=server.http_lifespan,
        )
        async with running_app(gateway) as (client, transport):
            sibling = await client.get("/other")
            anonymous = await client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
            http_client = httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": "Bearer good-token"},
            )
            async with streamable_http_client(
                RESOURCE_URL, http_client=http_client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("test_whoami", {})
        assert sibling.text == "gateway"
        assert anonymous.status_code == 401
        assert json.loads(result.content[0].text)["subject"] == "user-1"

    async def test_serve_metadata_false_suppresses_well_known_but_keeps_challenge(self):
        cfg = make_auth()
        cfg.serve_metadata = False
        server = MCPServer(prefix="test", auth=cfg)
        app = await server.build_http_app()
        async with running_app(app) as (client, _):
            metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
            anonymous = await client.post("/mcp", json=INIT_BODY, headers=MCP_HEADERS)
        assert metadata.status_code == 404
        assert anonymous.status_code == 401
        assert (
            "/.well-known/oauth-protected-resource/mcp"
            in anonymous.headers["www-authenticate"]
        )

    async def test_sse_paths_are_configurable_and_mount_under_prefix(self):
        # ASGITransport buffers whole responses, so an open SSE stream never
        # returns through it; serve through uvicorn on a free port instead.
        import asyncio
        import socket

        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount

        server = MCPServer(prefix="test")
        app = await server.build_sse_app(sse_path="/events", messages_path="/post/")
        gateway = Starlette(routes=[Mount("/api", app=app)])

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = uvicorn.Config(gateway, host="127.0.0.1", port=port, log_level="error")
        uv = uvicorn.Server(config)
        task = asyncio.create_task(uv.serve())
        try:
            while not uv.started:
                await asyncio.sleep(0.02)
            first = ""
            async with httpx.AsyncClient(timeout=5) as client:
                async with client.stream(
                    "GET", f"http://127.0.0.1:{port}/api/events"
                ) as resp:
                    assert resp.status_code == 200
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            first = line
                            break
        finally:
            uv.should_exit = True
            await task
        assert "/api/post/?session_id=" in first
