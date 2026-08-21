"""Spindl — Python framework for building MCP servers.

Provides hierarchical tool name prefixing, skills guide tools,
and built-in response spooling for large data sets.
"""

from spindl.auth import AuthConfig, current_identity
from spindl.prefix import PrefixResolver
from spindl.registry import ToolRegistry
from spindl.responses.envelope import ResponseEnvelope, ResponseMetadata
from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.server import MCPServer
from spindl.spooler.config import SpoolerConfig
from spindl.tool import BaseTool

__all__ = [
    "MCPServer",
    "BaseTool",
    "SpoolerConfig",
    "AuthConfig",
    "current_identity",
    "PrefixResolver",
    "ToolRegistry",
    "ResponseEnvelope",
    "ResponseMetadata",
    "StructuredError",
    "ErrorDetail",
]
