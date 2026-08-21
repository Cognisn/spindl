"""Tool registry for spindl MCP servers.

Manages tool registration, lookup by prefixed wire name, and
MCP protocol tool definitions. Tools are stored internally by
bare name; prefixing happens at the boundary.
"""

import logging
from typing import Any

from spindl.prefix import PrefixResolver
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Stores registered tools and mediates prefix resolution.

    Tools are keyed by their bare name internally. All public-facing
    methods (MCP definitions, guide rendering, tool lookup by wire
    name) go through the PrefixResolver.
    """

    def __init__(self, prefix_resolver: PrefixResolver) -> None:
        self._prefix_resolver = prefix_resolver
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance.

        Raises ValueError if a tool with the same bare name is
        already registered.
        """
        if not tool.name:
            raise ValueError("Tool must have a non-empty name")
        if tool.name in self._tools:
            raise ValueError(f"Tool name '{tool.name}' is already registered")
        self._tools[tool.name] = tool
        self._prefix_resolver.register_known_name(tool.name)
        logger.debug(
            "Registered tool '%s' (wire: '%s')",
            tool.name,
            self._prefix_resolver.prefixed_name(tool.name),
        )

    def get_tool(self, wire_name: str) -> BaseTool | None:
        """Look up a tool by its prefixed wire name.

        Returns None if the wire name doesn't match the current
        prefix or no tool with that bare name is registered.
        """
        bare_name = self._prefix_resolver.strip_prefix(wire_name)
        if bare_name is None:
            return None
        return self._tools.get(bare_name)

    def get_mcp_tool_definitions(self) -> list[Any]:
        """Return MCP Tool objects with prefixed names.

        Imports mcp.types.Tool lazily to avoid hard dependency
        at import time.
        """
        from mcp.types import Tool

        # Validate through the wire alias: the field is ``inputSchema`` on
        # mcp 1.x and ``input_schema`` (alias ``inputSchema``) on 2.x.
        return [
            Tool.model_validate(
                {
                    "name": self._prefix_resolver.prefixed_name(tool.name),
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
            )
            for tool in self._tools.values()
        ]

    def get_tool_guide(self, wire_name: str) -> str | None:
        """Return the fully resolved guide for a tool.

        Calls tool.guide() and then resolves all @placeholders
        to prefixed wire names.
        """
        tool = self.get_tool(wire_name)
        if tool is None:
            return None
        raw_guide = tool.guide()
        return self._prefix_resolver.resolve_placeholders(raw_guide)

    def list_tools_metadata(self) -> list[dict[str, str]]:
        """Return metadata for all tools, grouped by category.

        Each entry includes the prefixed wire name, category,
        and description.
        """
        result = []
        for tool in self._tools.values():
            result.append(
                {
                    "name": self._prefix_resolver.prefixed_name(tool.name),
                    "category": tool.category,
                    "description": tool.description,
                }
            )
        # Sort by category then name for consistent output
        result.sort(key=lambda t: (t["category"], t["name"]))
        return result

    @property
    def tool_count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Bare-name to tool mapping (read-only view)."""
        return dict(self._tools)

    @property
    def prefix_resolver(self) -> PrefixResolver:
        """The prefix resolver used by this registry."""
        return self._prefix_resolver
