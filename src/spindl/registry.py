"""Tool registry for spindl MCP servers.

Manages tool registration, lookup by prefixed wire name, and
MCP protocol tool definitions. Tools are stored internally by
bare name; prefixing happens at the boundary.

Every public lookup also applies the optional tool visibility hook, so
``tools/list``, ``tools/call`` and the skills guide tools all decide
visibility in this one place. A hidden tool is indistinguishable from
one that was never registered.
"""

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from spindl.prefix import PrefixResolver
from spindl.tool import BaseTool

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

ToolVisibility = Callable[[Optional["AccessToken"], BaseTool], bool]
"""Decides per request whether a tool is visible to the caller.

Receives the verified identity for the current request (the value of
:func:`spindl.auth.current_identity`, or ``None`` when authentication is
off) and the tool. Returns True when the tool is visible. It may be called
several times per request, so it should be quick and free of side effects.
An exception hides the tool (failing closed) and is logged.
"""


class ToolRegistry:
    """Stores registered tools and mediates prefix resolution.

    Tools are keyed by their bare name internally. All public-facing
    methods (MCP definitions, guide rendering, tool lookup by wire
    name) go through the PrefixResolver.
    """

    def __init__(
        self,
        prefix_resolver: PrefixResolver,
        visibility: Optional[ToolVisibility] = None,
    ) -> None:
        self._prefix_resolver = prefix_resolver
        self._tools: dict[str, BaseTool] = {}
        self._visibility = visibility

    def set_visibility(self, visibility: Optional[ToolVisibility]) -> None:
        """Install (or remove, with None) the per-request visibility hook."""
        self._visibility = visibility

    def is_visible(self, tool: BaseTool) -> bool:
        """Whether ``tool`` is visible to the caller of the current request."""
        if self._visibility is None:
            return True
        from spindl.auth import current_identity

        try:
            return bool(self._visibility(current_identity(), tool))
        except Exception:
            logger.warning(
                "Tool visibility hook failed for '%s'; hiding the tool",
                tool.name,
                exc_info=True,
            )
            return False

    def _visible_tools(self) -> list[BaseTool]:
        return [tool for tool in self._tools.values() if self.is_visible(tool)]

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
        prefix, no tool with that bare name is registered, or the
        tool is hidden from the current caller.
        """
        bare_name = self._prefix_resolver.strip_prefix(wire_name)
        if bare_name is None:
            return None
        tool = self._tools.get(bare_name)
        if tool is None or not self.is_visible(tool):
            return None
        return tool

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
            for tool in self._visible_tools()
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
        for tool in self._visible_tools():
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
        """Bare-name to tool mapping of every registered tool, ignoring visibility."""
        return dict(self._tools)

    @property
    def prefix_resolver(self) -> PrefixResolver:
        """The prefix resolver used by this registry."""
        return self._prefix_resolver
