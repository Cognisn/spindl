"""Hierarchical prefix resolver for MCP tool name namespacing.

Handles two-layer prefixing:
  - Level 1 (code): Server prefix set by the developer (e.g. "secops")
  - Level 2 (runtime): Instance prefix from HTTP header or env var

Combined wire names follow the pattern:
  {instance}_{server}_{tool}  or  {server}_{tool}

Tool guides use @tool_name placeholder syntax which gets resolved
to the fully prefixed wire name at render time.
"""

import os
import re
from contextvars import ContextVar
from typing import Optional

# Per-request instance prefix, set by HTTP transport middleware.
_instance_prefix_var: ContextVar[Optional[str]] = ContextVar(
    "spindl_instance_prefix", default=None
)

# Matches @tool_name placeholders in guide text.
_PLACEHOLDER_RE = re.compile(r"@([a-z][a-z0-9_]*)")


class PrefixResolver:
    """Resolves hierarchical tool name prefixes and @placeholders.

    The resolver maintains a set of known bare tool names so that
    only valid @references are replaced in guide text. Unknown
    @references are left untouched.
    """

    def __init__(self, server_prefix: str) -> None:
        if not server_prefix or not server_prefix.strip():
            raise ValueError("server_prefix must be a non-empty string")
        self._server_prefix = server_prefix.lower().strip().strip("_")
        self._known_names: set[str] = set()

    @property
    def server_prefix(self) -> str:
        """The developer-defined server prefix."""
        return self._server_prefix

    @property
    def instance_prefix(self) -> str | None:
        """The runtime instance prefix.

        Resolution order:
        1. Per-request context var (set by HTTP middleware)
        2. SPINDL_INSTANCE_PREFIX environment variable
        3. None
        """
        ctx = _instance_prefix_var.get(None)
        if ctx is not None:
            return ctx
        env = os.environ.get("SPINDL_INSTANCE_PREFIX")
        if env and env.strip():
            return env.strip().lower().strip("_")
        return None

    @property
    def full_prefix(self) -> str:
        """The combined prefix: {instance}_{server} or just {server}."""
        inst = self.instance_prefix
        if inst:
            return f"{inst}_{self._server_prefix}"
        return self._server_prefix

    def set_instance_prefix(self, prefix: str | None) -> None:
        """Set the per-request instance prefix via context var.

        Called by the HTTP transport middleware when an
        X-Spindl-Prefix header is present.
        """
        if prefix is not None:
            prefix = prefix.strip().lower().strip("_") or None
        _instance_prefix_var.set(prefix)

    def prefixed_name(self, bare_name: str) -> str:
        """Return the fully prefixed wire name for a bare tool name."""
        return f"{self.full_prefix}_{bare_name}"

    def register_known_name(self, bare_name: str) -> None:
        """Register a bare tool name for @placeholder resolution."""
        self._known_names.add(bare_name)

    def resolve_placeholders(self, text: str) -> str:
        """Replace @tool_name placeholders with prefixed wire names.

        Only replaces @references that match a registered tool name.
        Unknown @references are left untouched.
        """

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in self._known_names:
                return self.prefixed_name(name)
            return match.group(0)

        return _PLACEHOLDER_RE.sub(_replace, text)

    def strip_prefix(self, wire_name: str) -> str | None:
        """Extract the bare tool name from a prefixed wire name.

        Returns None if the wire name does not start with the
        current full prefix.
        """
        prefix = self.full_prefix + "_"
        if wire_name.startswith(prefix):
            return wire_name[len(prefix) :]
        return None

    @property
    def known_names(self) -> frozenset[str]:
        """The set of registered bare tool names."""
        return frozenset(self._known_names)
