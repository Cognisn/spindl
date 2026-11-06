"""Tool annotations: title, behaviour hints and category on ``tools/list``.

A tool declares ``title``, ``read_only``, ``destructive``, ``idempotent`` and
``open_world`` as class attributes. Only declared values reach the wire, so a
host applies the MCP defaults to anything left undeclared and the tool lands
in its stricter group. The category travels in ``_meta`` under one spindl
key. Registration refuses a tool that is both read-only and destructive, and
start-up warns about every tool that declares neither hint.
"""

import logging
from typing import Any

import pytest

from spindl.prefix import PrefixResolver
from spindl.registry import CATEGORY_META_KEY, ToolRegistry
from spindl.server import MCPServer
from spindl.skills.describe_tool import DescribeToolTool
from spindl.skills.list_tools import ListToolsTool
from spindl.spooler.config import SpoolerConfig
from spindl.spooler.tools.aggregate import SpoolerAggregateTool
from spindl.spooler.tools.distinct import SpoolerDistinctTool
from spindl.spooler.tools.list_spools import SpoolerListSpoolsTool
from spindl.spooler.tools.query import SpoolerQueryTool
from spindl.tool import BaseTool
from tests.test_protocol import (
    HTTP_BUILDERS,
    MODERN_HEADERS,
    TRACE_META,
    AppBuilder,
    http_client_for,
    http_mcp_client,
    in_memory_client,
    rpc,
)

BUILT_IN_TOOLS: list[type[BaseTool]] = [
    ListToolsTool,
    DescribeToolTool,
    SpoolerListSpoolsTool,
    SpoolerQueryTool,
    SpoolerAggregateTool,
    SpoolerDistinctTool,
]


class ReadDevices(BaseTool):
    name = "read_devices"
    description = "Read the device inventory"
    category = "inventory"
    title = "Read devices"
    read_only = True
    destructive = False
    idempotent = True
    open_world = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": []}


class WipeDevice(BaseTool):
    name = "wipe_device"
    description = "Wipe a device"
    category = "inventory"
    destructive = True

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {}}


class Undeclared(BaseTool):
    name = "undeclared"
    description = "A tool that declares nothing"
    category = ""

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {}}


class TitledOnly(BaseTool):
    name = "titled_only"
    description = "A tool with a title and no hints"
    category = "general"
    title = "Titled only"

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {}}


def make_server(hook: Any = None) -> MCPServer:
    server = MCPServer(prefix="test", tool_visibility=hook)
    server.register_all([ReadDevices(), WipeDevice(), Undeclared(), TitledOnly()])
    return server


def wire_tool(listing: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [tool for tool in listing["tools"] if tool["name"] == name]
    assert len(matches) == 1, f"{name} not listed once"
    return matches[0]


async def raw_tools_list(
    server: MCPServer, build: AppBuilder, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    async with http_client_for(server, build) as http_client:
        resp = await http_client.post(
            "/mcp",
            json=rpc("tools/list", {}),
            headers={**MODERN_HEADERS, "Mcp-Method": "tools/list", **(headers or {})},
        )
    assert resp.status_code == 200
    result: dict[str, Any] = resp.json()["result"]
    return result


class TestDeclarations:
    def test_every_annotation_defaults_to_undeclared(self):
        assert BaseTool.title is None
        assert BaseTool.read_only is None
        assert BaseTool.destructive is None
        assert BaseTool.idempotent is None
        assert BaseTool.open_world is None

    def test_category_meta_key_follows_the_spec_naming_rules(self):
        assert CATEGORY_META_KEY == "com.cognisn.spindl/category"


class TestDefinitions:
    def definitions(self, *tools: BaseTool) -> dict[str, dict[str, Any]]:
        registry = ToolRegistry(PrefixResolver("test"))
        for tool in tools:
            registry.register(tool)
        return {
            tool.name: tool.model_dump(by_alias=True, exclude_none=True)
            for tool in registry.get_mcp_tool_definitions()
        }

    def test_declared_tool_sends_title_annotations_and_category(self):
        wire = self.definitions(ReadDevices())["test_read_devices"]
        assert wire["title"] == "Read devices"
        assert wire["annotations"] == {
            "title": "Read devices",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        assert wire["_meta"] == {"com.cognisn.spindl/category": "inventory"}

    def test_only_declared_hints_are_sent(self):
        definition = self.definitions(WipeDevice())["test_wipe_device"]
        assert definition["annotations"] == {"destructiveHint": True}
        assert "title" not in definition

    def test_undeclared_tool_sends_no_annotations_title_or_meta(self):
        definition = self.definitions(Undeclared())["test_undeclared"]
        assert set(definition) == {"name", "description", "inputSchema"}

    def test_title_alone_sends_title_without_hints(self):
        definition = self.definitions(TitledOnly())["test_titled_only"]
        assert definition["title"] == "Titled only"
        assert definition["annotations"] == {"title": "Titled only"}


class TestContradiction:
    def test_read_only_and_destructive_together_is_refused(self):
        class Contradictory(BaseTool):
            name = "contradictory"
            read_only = True
            destructive = True

        registry = ToolRegistry(PrefixResolver("test"))
        with pytest.raises(ValueError, match="'contradictory'.*read_only.*destruct"):
            registry.register(Contradictory())
        assert registry.tool_count == 0

    def test_server_register_refuses_it_too(self):
        class Contradictory(BaseTool):
            name = "contradictory"
            read_only = True
            destructive = True

        with pytest.raises(ValueError, match="contradictory"):
            MCPServer(prefix="test").register(Contradictory())

    @pytest.mark.parametrize(
        ("read_only", "destructive"),
        [(True, False), (False, True), (False, False), (True, None), (None, True)],
    )
    def test_consistent_declarations_are_accepted(self, read_only, destructive):
        class Consistent(BaseTool):
            name = "consistent"

        Consistent.read_only = read_only
        Consistent.destructive = destructive
        registry = ToolRegistry(PrefixResolver("test"))
        registry.register(Consistent())
        assert registry.tool_count == 1


class TestStartupWarning:
    def warnings(self, caplog: pytest.LogCaptureFixture) -> list[str]:
        return [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "neither read_only nor destructive" in record.getMessage()
        ]

    async def test_names_every_tool_declaring_neither_hint(self, caplog):
        caplog.set_level(logging.WARNING)
        server = make_server()
        await server._setup()
        await server._setup()
        messages = self.warnings(caplog)
        assert messages == [
            "2 tool(s) declare neither read_only nor destructive, so hosts "
            "treat them as possibly destructive: titled_only, undeclared. "
            "Set read_only or destructive on each tool class."
        ]

    async def test_built_ins_never_trigger_the_warning(self, caplog, tmp_path):
        caplog.set_level(logging.WARNING)
        server = MCPServer(
            prefix="test",
            spooler=SpoolerConfig(db_path=str(tmp_path / "spool.db")),
        )
        server.register(ReadDevices())
        server.register(WipeDevice())
        await server._setup()
        assert self.warnings(caplog) == []

    async def test_a_false_hint_counts_as_declared(self, caplog):
        class WritesOnly(BaseTool):
            name = "writes_only"
            read_only = False

        caplog.set_level(logging.WARNING)
        server = MCPServer(prefix="test")
        server.register(WritesOnly())
        await server._setup()
        assert self.warnings(caplog) == []


class TestBuiltIns:
    @pytest.mark.parametrize("tool_cls", BUILT_IN_TOOLS, ids=lambda c: c.name)
    def test_built_in_tool_is_read_only_and_idempotent(self, tool_cls):
        assert tool_cls.read_only is True
        assert tool_cls.destructive is False
        assert tool_cls.idempotent is True
        assert tool_cls.open_world is False
        assert tool_cls.title

    async def test_built_ins_on_the_wire(self, tmp_path):
        server = MCPServer(
            prefix="test",
            spooler=SpoolerConfig(db_path=str(tmp_path / "spool.db")),
        )
        async with in_memory_client(server) as client:
            tools = (await client.list_tools(meta=TRACE_META)).tools
        built_ins = {f"test_{cls.name}" for cls in BUILT_IN_TOOLS}
        listed = {tool.name: tool for tool in tools}
        assert built_ins <= set(listed)
        for name in built_ins:
            annotations = listed[name].annotations
            assert annotations is not None
            assert annotations.read_only_hint is True
            assert annotations.destructive_hint is False
            assert annotations.idempotent_hint is True
            assert annotations.open_world_hint is False
            assert listed[name].title


class TestListToolsMetadata:
    def test_includes_title_and_hints_in_category_order(self):
        registry = ToolRegistry(PrefixResolver("test"))
        for tool in (WipeDevice(), TitledOnly(), ReadDevices(), Undeclared()):
            registry.register(tool)
        assert registry.list_tools_metadata() == [
            {
                "name": "test_undeclared",
                "title": None,
                "category": "",
                "description": "A tool that declares nothing",
                "read_only": None,
                "destructive": None,
            },
            {
                "name": "test_titled_only",
                "title": "Titled only",
                "category": "general",
                "description": "A tool with a title and no hints",
                "read_only": None,
                "destructive": None,
            },
            {
                "name": "test_read_devices",
                "title": "Read devices",
                "category": "inventory",
                "description": "Read the device inventory",
                "read_only": True,
                "destructive": False,
            },
            {
                "name": "test_wipe_device",
                "title": None,
                "category": "inventory",
                "description": "Wipe a device",
                "read_only": None,
                "destructive": True,
            },
        ]

    async def test_list_tools_skill_returns_title_and_hints(self):
        registry = ToolRegistry(PrefixResolver("test"))
        registry.register(ReadDevices())
        registry.register(ListToolsTool(registry=registry))
        result = await ListToolsTool(registry=registry).execute()
        assert result["data"]["categories"]["inventory"] == [
            {
                "name": "test_read_devices",
                "title": "Read devices",
                "description": "Read the device inventory",
                "read_only": True,
                "destructive": False,
            }
        ]


class TestWire:
    async def test_in_memory_client_sees_declared_annotations(self):
        async with in_memory_client(make_server()) as client:
            tools = {
                t.name: t for t in (await client.list_tools(meta=TRACE_META)).tools
            }
        read = tools["test_read_devices"]
        assert read.title == "Read devices"
        assert read.annotations is not None
        assert read.annotations.read_only_hint is True
        assert read.annotations.destructive_hint is False
        assert read.meta == {"com.cognisn.spindl/category": "inventory"}
        wipe = tools["test_wipe_device"]
        assert wipe.annotations is not None
        assert wipe.annotations.destructive_hint is True
        assert wipe.annotations.read_only_hint is None
        assert tools["test_undeclared"].annotations is None
        assert tools["test_undeclared"].meta is None

    @HTTP_BUILDERS
    async def test_streamable_http_sends_only_declared_hints(self, build):
        listing = await raw_tools_list(make_server(), build)
        read = wire_tool(listing, "test_read_devices")
        assert read["title"] == "Read devices"
        assert read["annotations"] == {
            "title": "Read devices",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        assert read["_meta"] == {"com.cognisn.spindl/category": "inventory"}
        wipe = wire_tool(listing, "test_wipe_device")
        assert wipe["annotations"] == {"destructiveHint": True}
        assert "title" not in wipe
        undeclared = wire_tool(listing, "test_undeclared")
        assert "annotations" not in undeclared
        assert "title" not in undeclared
        assert "_meta" not in undeclared

    @HTTP_BUILDERS
    async def test_streamable_http_client_sees_annotations(self, build):
        async with http_mcp_client(make_server(), build) as client:
            tools = {
                t.name: t for t in (await client.list_tools(meta=TRACE_META)).tools
            }
        assert tools["test_read_devices"].annotations is not None
        assert tools["test_read_devices"].annotations.read_only_hint is True
        assert tools["test_undeclared"].annotations is None

    @HTTP_BUILDERS
    async def test_instance_prefix_names_annotated_tools(self, build):
        listing = await raw_tools_list(
            make_server(), build, headers={"X-Spindl-Prefix": "lab"}
        )
        read = wire_tool(listing, "lab_test_read_devices")
        assert read["annotations"]["readOnlyHint"] is True
        assert read["_meta"] == {"com.cognisn.spindl/category": "inventory"}

    @HTTP_BUILDERS
    async def test_visibility_still_hides_annotated_tools(self, build):
        def hide_read(identity: Any, tool: BaseTool) -> bool:
            return tool.name != "read_devices"

        listing = await raw_tools_list(make_server(hide_read), build)
        names = {tool["name"] for tool in listing["tools"]}
        assert "test_read_devices" not in names
        assert "test_wipe_device" in names
