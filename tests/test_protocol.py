"""Protocol tests: spindl speaks MCP 2026-07-28 on every transport.

Covers the in-memory client, the streamable HTTP endpoint (embedded through
``http_endpoint`` and served by ``build_http_app``) and the SSE transport:
the negotiated protocol version, ``server/discover``, ``tools/list`` and
``tools/call`` with per-request ``_meta``, the ``Mcp-Method`` and ``Mcp-Name``
header checks, and the ``X-Spindl-Prefix`` instance prefix.
"""

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import HEADER_MISMATCH, LATEST_PROTOCOL_VERSION
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Route

from spindl.server import MCPServer
from spindl.tool import BaseTool

BASE_URL = "http://testserver"
TRACE_META = {"example.com/trace-id": "4bf92f3577b34da6"}
ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "example-client", "version": "1"},
}
MODERN_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2026-07-28",
}
# The SSE tests need a real socket. Port 0 asks the OS for a free one; set
# SPINDL_TEST_PORT to keep the listener inside a reserved block.
TEST_PORT = int(os.environ.get("SPINDL_TEST_PORT", "0"))


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo the given text"
    category = "general"

    class InputModel(BaseModel):
        text: str = "hello"

    def guide(self) -> str:
        return "Call @echo."

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {"text": params.get("text", "hello")}}


class ApproveTool(BaseTool):
    name = "approve"
    description = "Approve a change"
    category = "general"

    def guide(self) -> str:
        return "Call @approve."

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {"approved": True}}


def hide_approve(identity: Any, tool: BaseTool) -> bool:
    return tool.name != "approve"


def make_server(hook: Any = None) -> MCPServer:
    server = MCPServer(prefix="test", tool_visibility=hook)
    server.register(EchoTool())
    server.register(ApproveTool())
    return server


def payload(result: Any) -> Any:
    return json.loads(result.content[0].text)


async def build_with_http_app(server: MCPServer) -> Starlette:
    app: Starlette = await server.build_http_app()
    return app


async def build_with_http_endpoint(server: MCPServer) -> Starlette:
    endpoint = await server.http_endpoint()
    return Starlette(
        routes=[Route("/mcp", endpoint, methods=["POST", "GET", "DELETE"])],
        lifespan=server.http_lifespan,
    )


HTTP_BUILDERS = pytest.mark.parametrize(
    "build",
    [build_with_http_app, build_with_http_endpoint],
    ids=["build_http_app", "http_endpoint"],
)

AppBuilder = Callable[[MCPServer], Awaitable[Starlette]]


@asynccontextmanager
async def http_client_for(
    server: MCPServer, build: AppBuilder
) -> AsyncIterator[httpx2.AsyncClient]:
    app = await build(server)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=BASE_URL
        ) as http_client:
            yield http_client


@asynccontextmanager
async def http_mcp_client(
    server: MCPServer, build: AppBuilder, headers: dict[str, str] | None = None
) -> AsyncIterator[Client]:
    async with http_client_for(server, build) as http_client:
        http_client.headers.update(headers or {})
        transport = streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client)
        async with Client(transport, cache=None) as client:
            yield client


@asynccontextmanager
async def in_memory_client(server: MCPServer) -> AsyncIterator[Client]:
    await server._setup()
    async with Client(server._mcp_server, cache=None) as client:
        yield client


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
        yield f"http://127.0.0.1:{port}/sse"
    finally:
        uv_server.should_exit = True
        await task


@asynccontextmanager
async def sse_mcp_client(
    server: MCPServer, headers: dict[str, str] | None = None
) -> AsyncIterator[Client]:
    async with running_sse_server(server) as url:
        async with Client(sse_client(url, headers=headers), cache=None) as client:
            yield client


async def tool_names(client: Client) -> set[str]:
    return {tool.name for tool in (await client.list_tools(meta=TRACE_META)).tools}


def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {**params, "_meta": {**ENVELOPE, **TRACE_META}},
    }


class TestInMemory:
    async def test_negotiates_the_latest_protocol_version(self):
        async with in_memory_client(make_server()) as client:
            assert LATEST_PROTOCOL_VERSION == "2026-07-28"
            assert client.protocol_version == LATEST_PROTOCOL_VERSION

    async def test_answers_server_discover(self):
        async with in_memory_client(make_server()) as client:
            discovered = client.session.discover_result
            assert discovered is not None
            assert LATEST_PROTOCOL_VERSION in discovered.supported_versions
            assert discovered.capabilities.tools is not None

    async def test_tools_list_and_call_with_per_request_meta(self):
        async with in_memory_client(make_server()) as client:
            names = await tool_names(client)
            result = await client.call_tool(
                "test_echo", {"text": "hi"}, meta=TRACE_META
            )
        assert {"test_echo", "test_approve", "test_list_tools"} <= names
        assert payload(result) == {"success": True, "data": {"text": "hi"}}

    async def test_unknown_argument_is_refused(self):
        async with in_memory_client(make_server()) as client:
            result = await client.call_tool(
                "test_echo", {"text": "hi", "colour": "red"}, meta=TRACE_META
            )
        body = payload(result)
        assert body["success"] is False
        assert body["error"]["error_code"] == "INVALID_ARGUMENTS"

    async def test_visibility_hook_governs_tools_list_and_tools_call(self):
        async with in_memory_client(make_server(hide_approve)) as client:
            names = await tool_names(client)
            result = await client.call_tool("test_approve", {}, meta=TRACE_META)
        assert "test_approve" not in names and "test_echo" in names
        assert payload(result)["error"]["error_code"] == "TOOL_NOT_FOUND"


class TestStreamableHttp:
    @HTTP_BUILDERS
    async def test_negotiates_the_latest_protocol_version(self, build):
        async with http_mcp_client(make_server(), build) as client:
            assert client.protocol_version == LATEST_PROTOCOL_VERSION
            assert client.session.discover_result is not None

    @HTTP_BUILDERS
    async def test_tools_list_and_call_with_per_request_meta(self, build):
        async with http_mcp_client(make_server(), build) as client:
            names = await tool_names(client)
            result = await client.call_tool(
                "test_echo", {"text": "hi"}, meta=TRACE_META
            )
        assert {"test_echo", "test_approve"} <= names
        assert payload(result) == {"success": True, "data": {"text": "hi"}}

    @HTTP_BUILDERS
    async def test_server_discover_over_the_wire(self, build):
        async with http_client_for(make_server(), build) as http_client:
            resp = await http_client.post(
                "/mcp",
                json=rpc("server/discover", {}),
                headers={**MODERN_HEADERS, "Mcp-Method": "server/discover"},
            )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert LATEST_PROTOCOL_VERSION in result["supportedVersions"]
        assert "tools" in result["capabilities"]
        assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "test"

    @HTTP_BUILDERS
    async def test_tools_list_is_never_publicly_cacheable(self, build):
        # Visibility and the instance prefix vary the listing per request, so
        # a shared cache must never serve one caller's list to another.
        async with http_client_for(make_server(), build) as http_client:
            resp = await http_client.post(
                "/mcp",
                json=rpc("tools/list", {}),
                headers={**MODERN_HEADERS, "Mcp-Method": "tools/list"},
            )
        assert resp.status_code == 200
        assert resp.json()["result"]["cacheScope"] == "private"

    @HTTP_BUILDERS
    async def test_matching_method_and_name_headers_are_accepted(self, build):
        async with http_client_for(make_server(), build) as http_client:
            resp = await http_client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_echo", "arguments": {}}),
                headers={
                    **MODERN_HEADERS,
                    "Mcp-Method": "tools/call",
                    "Mcp-Name": "test_echo",
                },
            )
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert json.loads(text) == {"success": True, "data": {"text": "hello"}}

    @HTTP_BUILDERS
    @pytest.mark.parametrize(
        "method_header, name_header",
        [
            ("tools/call", "test_approve"),
            ("tools/list", "test_echo"),
            ("tools/call", None),
        ],
        ids=["name-mismatch", "method-mismatch", "name-missing"],
    )
    async def test_mismatched_headers_are_rejected(
        self, build, method_header, name_header
    ):
        headers = {**MODERN_HEADERS, "Mcp-Method": method_header}
        if name_header is not None:
            headers["Mcp-Name"] = name_header
        async with http_client_for(make_server(), build) as http_client:
            resp = await http_client.post(
                "/mcp",
                json=rpc("tools/call", {"name": "test_echo", "arguments": {}}),
                headers=headers,
            )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == HEADER_MISMATCH

    @HTTP_BUILDERS
    async def test_instance_prefix_header(self, build):
        async with http_mcp_client(
            make_server(), build, headers={"X-Spindl-Prefix": "prod"}
        ) as client:
            names = await tool_names(client)
            result = await client.call_tool("prod_test_echo", {}, meta=TRACE_META)
        assert "prod_test_echo" in names and "test_echo" not in names
        assert payload(result)["success"] is True

    @HTTP_BUILDERS
    async def test_instance_prefix_header_on_a_handshake_era_request(self, build):
        async with http_client_for(make_server(), build) as http_client:
            resp = await http_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "X-Spindl-Prefix": "prod",
                },
            )
        names = {tool["name"] for tool in resp.json()["result"]["tools"]}
        assert "prod_test_echo" in names


class TestSse:
    async def test_negotiates_the_latest_protocol_version(self):
        async with sse_mcp_client(make_server()) as client:
            assert client.protocol_version == LATEST_PROTOCOL_VERSION
            discovered = client.session.discover_result
            assert discovered is not None
            assert LATEST_PROTOCOL_VERSION in discovered.supported_versions

    async def test_tools_list_and_call_with_per_request_meta(self):
        async with sse_mcp_client(make_server()) as client:
            names = await tool_names(client)
            result = await client.call_tool(
                "test_echo", {"text": "hi"}, meta=TRACE_META
            )
        assert {"test_echo", "test_approve"} <= names
        assert payload(result) == {"success": True, "data": {"text": "hi"}}

    async def test_instance_prefix_header(self):
        async with sse_mcp_client(
            make_server(), headers={"X-Spindl-Prefix": "prod"}
        ) as client:
            names = await tool_names(client)
            result = await client.call_tool("prod_test_echo", {}, meta=TRACE_META)
        assert "prod_test_echo" in names and "test_echo" not in names
        assert payload(result)["success"] is True


class TestDependencyFloor:
    def _dependencies(self) -> list[str]:
        text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
        block = re.search(r"^dependencies = \[(.*?)^\]", text, re.M | re.S)
        assert block is not None
        return re.findall(r'"([^"]+)"', block.group(1))

    def test_requires_mcp_2_3_or_later_within_major_version_2(self):
        assert "mcp>=2.3,<3" in self._dependencies()

    def test_declares_starlette_directly(self):
        assert any(dep.startswith("starlette") for dep in self._dependencies())
