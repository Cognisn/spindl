"""Tests for ToolRegistry."""

import pytest

from spindl.prefix import PrefixResolver
from spindl.registry import ToolRegistry
from spindl.tool import BaseTool


class TestToolRegistry:
    def test_register_and_get(self, registry, sample_tool):
        registry.register(sample_tool)
        found = registry.get_tool("test_get_devices")
        assert found is sample_tool

    def test_get_wrong_prefix(self, registry, sample_tool):
        registry.register(sample_tool)
        assert registry.get_tool("other_get_devices") is None

    def test_get_unregistered(self, registry):
        assert registry.get_tool("test_nonexistent") is None

    def test_duplicate_raises(self, registry, sample_tool):
        registry.register(sample_tool)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(sample_tool)

    def test_empty_name_raises(self, registry):
        class NoName(BaseTool):
            description = "test"
            category = "test"

        tool = NoName()
        with pytest.raises(ValueError, match="non-empty"):
            registry.register(tool)

    def test_tool_count(self, registry, sample_tool):
        assert registry.tool_count == 0
        registry.register(sample_tool)
        assert registry.tool_count == 1

    def test_list_tools_metadata(self, registry, sample_tool):
        registry.register(sample_tool)
        meta = registry.list_tools_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "test_get_devices"
        assert meta[0]["category"] == "inventory"
        assert meta[0]["description"] == "List devices"

    def test_get_tool_guide_resolves_placeholders(self, registry, sample_tool):
        registry.register(sample_tool)

        # Also register spooler_query so the placeholder resolves
        class FakeSpoolerQuery(BaseTool):
            name = "spooler_query"
            description = "Query"
            category = "spooler"

            async def execute(self, **params):
                return {}

        registry.register(FakeSpoolerQuery())

        guide = registry.get_tool_guide("test_get_devices")
        assert guide is not None
        assert "test_get_devices" in guide
        assert "test_spooler_query" in guide
        assert "@" not in guide  # all placeholders resolved

    def test_get_tool_guide_not_found(self, registry):
        assert registry.get_tool_guide("test_nonexistent") is None

    def test_get_mcp_definitions(self, registry, sample_tool):
        registry.register(sample_tool)
        defs = registry.get_mcp_tool_definitions()
        assert len(defs) == 1
        assert defs[0].name == "test_get_devices"
        assert defs[0].description == "List devices"

    def test_tools_property(self, registry, sample_tool):
        registry.register(sample_tool)
        tools = registry.tools
        assert "get_devices" in tools
        assert tools["get_devices"] is sample_tool
