"""Tests for the per-request tool visibility hook and the exact metadata strings."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken

from spindl.auth import AuthConfig
from spindl.server import MCPServer
from spindl.spooler.config import SpoolerConfig
from spindl.tool import BaseTool

RESOURCE_URL = "http://testserver/mcp"
AUTH_SERVER_URL = "http://auth.example"


class Verifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token in ("token-a", "token-b"):
            return AccessToken(
                token=token, client_id=f"client-{token[-1]}", scopes=["read"]
            )
        return None


class EchoTool(BaseTool):
    category = "general"

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"The {name} tool"

    def guide(self) -> str:
        return f"# @{self.name}\n\nGuide for {self.name}."

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {"tool": self.name}}


def only_client_a_sees_approve(identity: AccessToken | None, tool: BaseTool) -> bool:
    if tool.name != "approve":
        return True
    return identity is not None and identity.client_id == "client-a"


def make_server(
    hook: Any = None, *, with_approve: bool = True, spooler: bool = False
) -> MCPServer:
    server = MCPServer(
        prefix="test",
        auth=AuthConfig(
            token_verifier=Verifier(),
            resource_server_url=RESOURCE_URL,
            authorization_servers=[AUTH_SERVER_URL],
            required_scopes=["read"],
        ),
        tool_visibility=hook,
        spooler=SpoolerConfig(db_path=":memory:") if spooler else None,
    )
    server.register(EchoTool("public"))
    if with_approve:
        server.register(EchoTool("approve"))
    return server


@asynccontextmanager
async def session_for(server: MCPServer, token: str):
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        http_client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        async with streamable_http_client(
            RESOURCE_URL, http_client=http_client
        ) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def tool_names(session: ClientSession) -> set[str]:
    return {tool.name for tool in (await session.list_tools()).tools}


async def call(
    session: ClientSession, name: str, arguments: dict[str, Any] | None = None
) -> Any:
    result = await session.call_tool(name, arguments or {})
    return json.loads(result.content[0].text)


class TestToolsList:
    async def test_hidden_tool_is_absent_from_tools_list(self):
        server = make_server(only_client_a_sees_approve)
        async with session_for(server, "token-b") as session:
            names = await tool_names(session)
        assert "test_approve" not in names
        assert "test_public" in names

    async def test_visible_tool_is_listed_for_the_allowed_identity(self):
        server = make_server(only_client_a_sees_approve)
        async with session_for(server, "token-a") as session:
            assert "test_approve" in await tool_names(session)


class TestToolsCall:
    async def test_hidden_tool_call_is_refused_exactly_like_an_unknown_tool(self):
        hidden_server = make_server(only_client_a_sees_approve)
        absent_server = make_server(None, with_approve=False)
        async with session_for(hidden_server, "token-b") as session:
            hidden = await session.call_tool("test_approve", {})
        async with session_for(absent_server, "token-b") as session:
            absent = await session.call_tool("test_approve", {})

        assert hidden.model_dump() == absent.model_dump()
        assert (
            json.loads(hidden.content[0].text)["error"]["error_code"]
            == "TOOL_NOT_FOUND"
        )

    async def test_visible_tool_call_runs(self):
        server = make_server(only_client_a_sees_approve)
        async with session_for(server, "token-a") as session:
            payload = await call(session, "test_approve")
        assert payload == {"success": True, "data": {"tool": "approve"}}


class TestDiscoveryPair:
    async def test_list_tools_never_lists_a_hidden_tool(self):
        server = make_server(only_client_a_sees_approve)
        async with session_for(server, "token-b") as session:
            payload = await call(session, "test_list_tools")
        listed = {
            t["name"] for group in payload["data"]["categories"].values() for t in group
        }
        assert "test_approve" not in listed
        assert "test_public" in listed
        assert payload["data"]["total_tools"] == len(listed)

    async def test_describe_tool_answers_for_a_hidden_tool_as_for_an_unknown_one(self):
        hidden_server = make_server(only_client_a_sees_approve)
        absent_server = make_server(None, with_approve=False)
        async with session_for(hidden_server, "token-b") as session:
            hidden = await call(
                session, "test_describe_tool", {"tool_name": "test_approve"}
            )
        async with session_for(absent_server, "token-b") as session:
            absent = await call(
                session, "test_describe_tool", {"tool_name": "test_approve"}
            )
        assert hidden == absent
        assert hidden["error"]["error_code"] == "TOOL_NOT_FOUND"

    async def test_describe_tool_works_for_the_allowed_identity(self):
        server = make_server(only_client_a_sees_approve)
        async with session_for(server, "token-a") as session:
            payload = await call(
                session, "test_describe_tool", {"tool_name": "test_approve"}
            )
        assert payload["guide"].startswith("# test_approve")


class TestPerRequest:
    async def test_decisions_differ_by_identity_in_concurrent_requests(self):
        server = make_server(only_client_a_sees_approve)
        app = await server.build_http_app()
        body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:

                async def listed(token: str) -> tuple[str, bool]:
                    resp = await client.post(
                        "/mcp",
                        json=body,
                        headers={**headers, "Authorization": f"Bearer {token}"},
                    )
                    names = {t["name"] for t in resp.json()["result"]["tools"]}
                    return token, "test_approve" in names

                results = await asyncio.gather(
                    *(listed("token-a" if n % 2 else "token-b") for n in range(40))
                )

        assert all(seen == (token == "token-a") for token, seen in results)

    async def test_hook_receives_none_when_auth_is_off(self):
        seen: list[Any] = []

        def record(identity: AccessToken | None, tool: BaseTool) -> bool:
            seen.append(identity)
            return tool.name != "approve"

        server = MCPServer(prefix="test", tool_visibility=record)
        server.register(EchoTool("public"))
        server.register(EchoTool("approve"))
        app = await server.build_http_app()
        body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                resp = await client.post("/mcp", json=body, headers=headers)
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert "test_approve" not in names and "test_public" in names
        assert seen and all(identity is None for identity in seen)

    async def test_a_failing_hook_hides_the_tool_and_logs(self, caplog):
        def broken(identity: AccessToken | None, tool: BaseTool) -> bool:
            if tool.name == "approve":
                raise RuntimeError("policy store unavailable")
            return True

        server = make_server(broken)
        caplog.set_level(logging.WARNING)
        async with session_for(server, "token-a") as session:
            names = await tool_names(session)
            payload = await call(session, "test_approve")
        assert "test_approve" not in names
        assert payload["error"]["error_code"] == "TOOL_NOT_FOUND"
        assert any("visibility" in r.getMessage() for r in caplog.records)


class TestDefaults:
    async def test_no_hook_leaves_behaviour_unchanged(self):
        server = make_server(None)
        async with session_for(server, "token-b") as session:
            names = await tool_names(session)
            payload = await call(session, "test_approve")
            listed = await call(session, "test_list_tools")
        assert {
            "test_public",
            "test_approve",
            "test_list_tools",
            "test_describe_tool",
        } <= names
        assert payload == {"success": True, "data": {"tool": "approve"}}
        assert listed["data"]["total_tools"] == len(names)

    async def test_spooler_tools_stay_visible_unless_the_hook_says_otherwise(self):
        server = make_server(only_client_a_sees_approve, spooler=True)
        async with session_for(server, "token-b") as session:
            names = await tool_names(session)
        assert {
            "test_spooler_list",
            "test_spooler_query",
            "test_spooler_aggregate",
            "test_spooler_distinct",
        } <= names


class TestMetadataStrings:
    async def test_protected_resource_metadata_carries_the_configured_strings_exactly(
        self,
    ):
        server = make_server(None)
        app = await server.build_http_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                resp = await client.get("/.well-known/oauth-protected-resource/mcp")
        body = resp.json()
        assert body["resource"] == RESOURCE_URL
        assert body["authorization_servers"] == [
            AUTH_SERVER_URL
        ]  # no trailing slash added

    async def test_trailing_slashes_given_in_configuration_are_kept(self):
        server = MCPServer(
            prefix="test",
            auth=AuthConfig(
                token_verifier=Verifier(),
                resource_server_url=RESOURCE_URL,
                authorization_servers=[
                    "http://auth.example/",
                    "https://second.example/issuer",
                ],
            ),
        )
        app = await server.build_http_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                body = (
                    await client.get("/.well-known/oauth-protected-resource/mcp")
                ).json()
        assert body["authorization_servers"] == [
            "http://auth.example/",
            "https://second.example/issuer",
        ]
