"""Tests for MCPServer."""

import asyncio

import pytest
from pydantic import BaseModel, Field

from spindl.server import MCPServer
from spindl.spooler.config import SpoolerConfig
from spindl.tool import BaseTool


class TestMCPServerSetup:
    @pytest.mark.asyncio
    async def test_skills_always_registered(self):
        server = MCPServer(prefix="demo")
        await server._setup()
        defs = server._registry.get_mcp_tool_definitions()
        names = [d.name for d in defs]
        assert "demo_list_tools" in names
        assert "demo_describe_tool" in names

    @pytest.mark.asyncio
    async def test_spooler_auto_registration(self, tmp_path):
        config = SpoolerConfig(
            db_path=str(tmp_path / "test.db"),
            db_cleanup_on_exit=False,
        )
        server = MCPServer(prefix="demo", spooler=config)
        await server._setup()
        defs = server._registry.get_mcp_tool_definitions()
        names = [d.name for d in defs]
        assert "demo_spooler_list" in names
        assert "demo_spooler_query" in names
        assert "demo_spooler_aggregate" in names
        assert "demo_spooler_distinct" in names
        # Skills should also be there
        assert "demo_list_tools" in names
        assert "demo_describe_tool" in names
        await server._cleanup()

    @pytest.mark.asyncio
    async def test_no_spooler_tools_without_config(self):
        server = MCPServer(prefix="demo")
        await server._setup()
        defs = server._registry.get_mcp_tool_definitions()
        names = [d.name for d in defs]
        assert "demo_spooler_list" not in names


class TestMCPServerToolCalls:
    @pytest.mark.asyncio
    async def test_call_registered_tool(self, sample_tool):
        server = MCPServer(prefix="demo")
        server.register(sample_tool)
        await server._setup()
        results = await server._handle_call_tool("demo_get_devices", {"limit": 10})
        assert len(results) == 1
        import json

        data = json.loads(results[0].text)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        server = MCPServer(prefix="demo")
        await server._setup()
        results = await server._handle_call_tool("demo_nonexistent", {})
        import json

        data = json.loads(results[0].text)
        assert data["success"] is False
        assert data["error"]["error_code"] == "TOOL_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_call_list_tools(self):
        server = MCPServer(prefix="demo")
        await server._setup()
        results = await server._handle_call_tool("demo_list_tools", {})
        import json

        data = json.loads(results[0].text)
        assert data["success"] is True
        assert "categories" in data["data"]

    @pytest.mark.asyncio
    async def test_call_describe_tool(self, sample_tool):
        server = MCPServer(prefix="demo")
        server.register(sample_tool)
        await server._setup()
        results = await server._handle_call_tool(
            "demo_describe_tool",
            {"tool_name": "demo_get_devices"},
        )
        import json

        data = json.loads(results[0].text)
        assert data["success"] is True
        assert "guide" in data
        # The guide should have resolved placeholders
        assert "demo_get_devices" in data["guide"]

    @pytest.mark.asyncio
    async def test_spooler_integration(self, tmp_path):
        """Tool with spooler_auto_detect gets response spooled."""

        class BigDataTool(BaseTool):
            name = "big_data"
            description = "Returns lots of data"
            category = "data"
            spooler_auto_detect = True

            async def execute(self, **params):
                items = [
                    {"id": i, "name": f"item-{i}", "value": i * 10} for i in range(50)
                ]
                return {"success": True, "data": items}

        config = SpoolerConfig(
            db_path=str(tmp_path / "test.db"),
            max_inline_items=5,
            max_inline_tokens=100,
            db_cleanup_on_exit=False,
        )
        server = MCPServer(prefix="demo", spooler=config)
        server.register(BigDataTool())
        await server._setup()

        results = await server._handle_call_tool("demo_big_data", {})
        import json

        data = json.loads(results[0].text)
        assert data["success"] is True
        assert "spooled_data" in data["data"]
        spool_info = data["data"]["spooled_data"][0]
        assert spool_info["total_records"] == 50
        # Guidance text should have resolved prefix
        assert "demo_spooler_query" in data["metadata"]["guidance"]

        await server._cleanup()


class TestMCPServerArgumentValidation:
    """Unknown arguments are rejected at the MCP boundary.

    An adopter tool that never validates its own parameters still gets
    the protection, because the boundary is where the input schema was
    advertised in the first place.
    """

    async def _call(self, tool, arguments):
        import json

        server = MCPServer(prefix="demo")
        server.register(tool)
        await server._setup()
        results = await server._handle_call_tool(f"demo_{tool.name}", arguments)
        return json.loads(results[0].text)

    @pytest.mark.asyncio
    async def test_unknown_argument_is_rejected(self, sample_tool):
        data = await self._call(sample_tool, {"limit": 10, "filters": []})
        assert data["success"] is False
        assert data["error"]["error_code"] == "INVALID_ARGUMENTS"
        assert "filters" in data["error"]["error_message"]
        assert "limit" in data["error"]["suggestion"]

    @pytest.mark.asyncio
    async def test_known_arguments_still_pass(self, sample_tool):
        data = await self._call(sample_tool, {"limit": 10})
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_opted_out_tool_keeps_unknown_arguments(self):
        class Lenient(BaseTool):
            name = "lenient"
            description = "Accepts anything"
            category = "demo"
            reject_unknown_arguments = False

            async def execute(self, **params):
                return {"success": True, "seen": sorted(params)}

        data = await self._call(Lenient(), {"anything": 1})
        assert data["seen"] == ["anything"]
