"""Tests for ``BaseTool.context``: per call, read-only and isolated."""

import asyncio
import json
from typing import Any

import httpx

from spindl.auth import AuthConfig, Credentials, Identity, ToolContext
from spindl.server import MCPServer
from spindl.tool import BaseTool

RESOURCE_URL = "http://testserver/mcp"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
IDENTITIES = {
    "alice-key": Identity(subject="alice", reach={"tenant": "t1"}),
    "bob-key": Identity(subject="bob", reach={"tenant": "t2"}),
}


class Keys:
    async def authenticate(self, credentials: Credentials) -> Identity | None:
        return IDENTITIES.get(credentials.headers.get("x-api-key", ""))

    async def authorise(self, identity: Identity, tool: BaseTool, action: str) -> bool:
        return True


class OverlapTool(BaseTool):
    """Holds every call until two are running at once, then reports its context."""

    name = "overlap"
    description = "Report the call's context after overlapping another call"
    category = "general"
    read_only = True

    def __init__(self) -> None:
        self.running = 0
        self.both = asyncio.Event()

    async def execute(self, **params: Any) -> dict[str, Any]:
        before = self.context
        self.running += 1
        if self.running >= 2:
            self.both.set()
        await asyncio.wait_for(self.both.wait(), timeout=10)
        await asyncio.sleep(0.01)
        after = self.context
        assert before is after
        assert after is not None and after.identity is not None
        return {
            "subject": after.identity.subject,
            "reach": after.reach,
            "prefix": after.instance_prefix,
        }


class AssignTool(BaseTool):
    name = "assign"
    description = "Tries to replace its own context"
    category = "general"
    read_only = True

    async def execute(self, **params: Any) -> dict[str, Any]:
        try:
            self.context = None  # type: ignore[misc]
        except AttributeError:
            return {"read_only": True}
        return {"read_only": False}


def make_server(tool: BaseTool) -> MCPServer:
    server = MCPServer(
        prefix="test",
        auth=AuthConfig(
            authenticator=Keys(),
            resource_server_url=RESOURCE_URL,
            authorization_servers=["http://auth.example"],
            credential_headers=["x-api-key"],
        ),
    )
    server.register(tool)
    return server


async def call(
    client: httpx.AsyncClient, key: str, name: str, **headers: str
) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }
    resp = await client.post(
        "/mcp", json=body, headers={**HEADERS, "X-API-Key": key, **headers}
    )
    result: dict[str, Any] = json.loads(resp.json()["result"]["content"][0]["text"])
    return result


async def run_with(server: MCPServer, scenario: Any) -> Any:
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await scenario(client)


class TestToolContext:
    def test_context_is_none_outside_a_call(self):
        assert OverlapTool().context is None

    def test_context_cannot_be_assigned_from_outside(self):
        tool = OverlapTool()
        try:
            tool.context = ToolContext(  # type: ignore[misc]
                identity=None, reach=None, instance_prefix=None
            )
        except AttributeError:
            pass
        else:
            raise AssertionError("BaseTool.context accepted an assignment")
        assert tool.context is None

    async def test_context_cannot_be_assigned_inside_a_call(self):
        server = make_server(AssignTool())
        payload = await run_with(
            server, lambda client: call(client, "alice-key", "test_assign")
        )
        assert payload == {"read_only": True}

    async def test_concurrent_calls_on_one_instance_see_their_own_context(self):
        tool = OverlapTool()
        server = make_server(tool)

        async def scenario(client: httpx.AsyncClient) -> Any:
            return await asyncio.gather(
                call(
                    client,
                    "alice-key",
                    "lab_test_overlap",
                    **{"X-Spindl-Prefix": "lab"},
                ),
                call(client, "bob-key", "test_overlap"),
            )

        alice, bob = await run_with(server, scenario)
        assert alice == {"subject": "alice", "reach": {"tenant": "t1"}, "prefix": "lab"}
        assert bob == {"subject": "bob", "reach": {"tenant": "t2"}, "prefix": None}
        assert tool.context is None

    async def test_context_is_cleared_after_a_call_in_the_same_task(self):
        tool = OverlapTool()
        tool.both.set()
        server = make_server(tool)
        await server._setup()
        from spindl.auth._context import reset_identity, set_identity

        token = set_identity(IDENTITIES["alice-key"])
        try:
            await server._handle_call_tool("test_overlap", {})
        finally:
            reset_identity(token)
        assert tool.context is None
