"""Tool registry for spindl MCP servers.

Manages tool registration, lookup by prefixed wire name, and
MCP protocol tool definitions. Tools are stored internally by
bare name; prefixing happens at the boundary.

Tool access is decided in this one place, so ``tools/list``, ``tools/call``
and the skills guide tools all agree. The server installs an access check
(:meth:`ToolRegistry.set_access`) built from the configured
``Authenticator``; the ``async`` lookups (:meth:`ToolRegistry.listed_tools`,
:meth:`ToolRegistry.tool_definitions`, :meth:`ToolRegistry.tool_guide` and
:meth:`ToolRegistry.tools_metadata`) apply it. A tool the caller may not
use is indistinguishable from one that was never registered.

The access check decides tool access only. It never limits what an allowed
tool touches: that is reach, which the tool applies from
``self.context.reach``.
"""

import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Callable, Optional

from spindl.auth._types import ToolAction, is_scope_token
from spindl.prefix import PrefixResolver
from spindl.tool import BaseTool

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

CATEGORY_META_KEY = "com.cognisn.spindl/category"
"""The ``_meta`` key that carries a tool's category on ``tools/list``.

Follows the MCP rules for ``_meta`` key names: a reverse-DNS prefix of
dot-separated labels the project controls, a slash, then the name. The
``modelcontextprotocol`` and ``mcp`` prefixes are reserved and not used.
"""

ToolVisibility = Callable[[Optional["AccessToken"], BaseTool], bool]
"""Decides per request whether a tool is visible to the caller.

Receives the verified identity for the current request (the value of
:func:`spindl.auth.current_identity`, or ``None`` when authentication is
off) and the tool. Returns True when the tool is visible. It may be called
several times per request, so it should be quick and free of side effects.
An exception hides the tool (failing closed) and is logged.

Deprecated since 0.5.0: implement ``spindl.auth.Authenticator`` and decide
access in its ``authorise`` method instead.
"""

AccessCheck = Callable[[BaseTool, ToolAction], Awaitable[bool]]
"""Decides, for the current request, whether a tool may be listed or called.

Installed by the server with :meth:`ToolRegistry.set_access`. It reads the
caller from the request context itself.
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
        self._access: Optional[AccessCheck] = None

    def set_access(self, access: Optional[AccessCheck]) -> None:
        """Install (or remove, with None) the per-request access check.

        Once installed, only the ``async`` lookups can answer, because the
        check is asynchronous; the synchronous ones raise RuntimeError.
        """
        self._access = access

    async def allows(self, tool: BaseTool, action: ToolAction) -> bool:
        """Whether the caller of the current request may list or call ``tool``.

        Applies the visibility hook (if any) and then the access check (if
        any). Tool access only: this never limits what the tool touches.
        """
        if self._visibility is not None and not self.is_visible(tool):
            return False
        if self._access is None:
            return True
        return await self._access(tool, action)

    async def listed_tools(self) -> list[BaseTool]:
        """Registered tools the caller of the current request may list."""
        return [
            tool for tool in self._tools.values() if await self.allows(tool, "list")
        ]

    def lookup(self, wire_name: str) -> BaseTool | None:
        """Look up a tool by wire name, ignoring tool access.

        For callers that apply access themselves (the server's call path).
        """
        bare_name = self._prefix_resolver.strip_prefix(wire_name)
        if bare_name is None:
            return None
        return self._tools.get(bare_name)

    def declared_permissions(self) -> list[str]:
        """Every permission any registered tool declares, sorted, de-duplicated."""
        return sorted({p for tool in self._tools.values() for p in tool.permissions})

    async def tool_definitions(self) -> list[Any]:
        """MCP Tool objects for the tools the current caller may list."""
        from mcp.types import Tool

        return [
            Tool.model_validate(self._wire_definition(tool))
            for tool in await self.listed_tools()
        ]

    async def tool_guide(self, wire_name: str) -> str | None:
        """The resolved guide for a tool the current caller may list, or None."""
        tool = self.lookup(wire_name)
        if tool is None or not await self.allows(tool, "list"):
            return None
        return self._prefix_resolver.resolve_placeholders(tool.guide())

    async def tools_metadata(self) -> list[dict[str, Any]]:
        """:meth:`list_tools_metadata` for the tools the current caller may list."""
        return self._metadata(await self.listed_tools())

    def _require_sync(self) -> None:
        if self._access is not None:
            raise RuntimeError(
                "This registry has an asynchronous access check; use the "
                "async lookups (listed_tools, tool_definitions, tool_guide, "
                "tools_metadata)"
            )

    def set_visibility(self, visibility: Optional[ToolVisibility]) -> None:
        """Install (or remove, with None) the per-request visibility hook."""
        self._visibility = visibility

    def is_visible(self, tool: BaseTool) -> bool:
        """Whether ``tool`` is visible to the caller of the current request."""
        if self._visibility is None:
            return True
        from spindl.auth import current_identity
        from spindl.auth.adapters import ToolVisibilityAuthoriser

        # The hook receives the 0.4.0 AccessToken (or None), and fails closed.
        return ToolVisibilityAuthoriser(self._visibility).check(
            current_identity(), tool
        )

    def _visible_tools(self) -> list[BaseTool]:
        self._require_sync()
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
        if tool.read_only is True and tool.destructive is True:
            raise ValueError(
                f"Tool '{tool.name}' declares read_only = True and "
                f"destructive = True; a read-only tool cannot be destructive. "
                f"Declare one or the other."
            )
        _check_permissions(tool)
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
        self._require_sync()
        tool = self.lookup(wire_name)
        if tool is None or not self.is_visible(tool):
            return None
        return tool

    def get_mcp_tool_definitions(self) -> list[Any]:
        """Return MCP Tool objects with prefixed names.

        Each definition carries the tool's title and only the annotation
        hints it declared, so an undeclared hint takes the specification's
        default on the host. A non-empty category is sent in ``_meta``
        under :data:`CATEGORY_META_KEY`.

        Imports mcp.types.Tool lazily to avoid hard dependency
        at import time.
        """
        from mcp.types import Tool

        return [
            Tool.model_validate(self._wire_definition(tool))
            for tool in self._visible_tools()
        ]

    def _wire_definition(self, tool: BaseTool) -> dict[str, Any]:
        """Build one tool's ``tools/list`` entry, keyed by wire field names."""
        definition: dict[str, Any] = {
            "name": self._prefix_resolver.prefixed_name(tool.name),
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        if tool.title is not None:
            definition["title"] = tool.title
        hints = {
            "title": tool.title,
            "readOnlyHint": tool.read_only,
            "destructiveHint": tool.destructive,
            "idempotentHint": tool.idempotent,
            "openWorldHint": tool.open_world,
        }
        annotations = {key: value for key, value in hints.items() if value is not None}
        if annotations:
            definition["annotations"] = annotations
        if tool.category:
            definition["_meta"] = {CATEGORY_META_KEY: tool.category}
        return definition

    def undeclared_tools(self) -> list[str]:
        """Bare names, sorted, of tools declaring neither read_only nor destructive."""
        return sorted(
            tool.name
            for tool in self._tools.values()
            if tool.read_only is None and tool.destructive is None
        )

    def warn_undeclared_tools(self) -> None:
        """Log one warning naming every tool that declares neither hint.

        Hosts apply the specification's defaults to such a tool and treat
        it as possibly destructive. Logs nothing when every tool declares
        ``read_only`` or ``destructive``.
        """
        names = self.undeclared_tools()
        if not names:
            return
        logger.warning(
            "%d tool(s) declare neither read_only nor destructive, so hosts "
            "treat them as possibly destructive: %s. Set read_only or "
            "destructive on each tool class.",
            len(names),
            ", ".join(names),
        )

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

    def list_tools_metadata(self) -> list[dict[str, Any]]:
        """Return metadata for all tools, grouped by category.

        Each entry includes the prefixed wire name, title, category,
        description, and the ``read_only`` and ``destructive`` values
        (``None`` when undeclared).
        """
        return self._metadata(self._visible_tools())

    def _metadata(self, tools: list[BaseTool]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool in tools:
            result.append(
                {
                    "name": self._prefix_resolver.prefixed_name(tool.name),
                    "title": tool.title,
                    "category": tool.category,
                    "description": tool.description,
                    "read_only": tool.read_only,
                    "destructive": tool.destructive,
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


def _check_permissions(tool: BaseTool) -> None:
    """Refuse permission names that are not OAuth scope tokens.

    They are advertised as ``scopes_supported`` and named in ``scope``
    challenges, so each must be a valid RFC 6749 scope token.
    """
    permissions: Any = tool.permissions
    if isinstance(permissions, str) or not isinstance(permissions, (list, tuple)):
        raise ValueError(
            f"Tool '{tool.name}' must declare permissions as a list of names, "
            f"not {type(permissions).__name__}"
        )
    for permission in permissions:
        if not is_scope_token(permission):
            raise ValueError(
                f"Tool '{tool.name}' declares the permission {permission!r}, "
                f"which is not a valid OAuth scope token (printable ASCII, no "
                f"spaces, quotes or backslashes)"
            )
