"""MCP Server orchestrator for spindl.

Provides the top-level MCPServer class that wires together the
PrefixResolver, ToolRegistry, MCP SDK Server, and optional
ResponseSpooler. Supports stdio, HTTP streamable, and SSE transports.
"""

import json
import logging
from typing import Any, Optional

from spindl.prefix import PrefixResolver
from spindl.registry import ToolRegistry
from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.spooler.config import SpoolerConfig
from spindl.spooler.spooler import ResponseSpooler
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class MCPServer:
    """Spindl MCP server with prefix namespacing and optional spooling.

    Usage::

        from spindl import MCPServer, BaseTool

        server = MCPServer(prefix="secops")
        server.register(MyTool())
        import asyncio
        asyncio.run(server.run_stdio())
    """

    def __init__(
        self,
        prefix: str,
        spooler: Optional[SpoolerConfig] = None,
        read_only: bool = False,
        server_name: Optional[str] = None,
    ) -> None:
        """Initialise the MCP server.

        Args:
            prefix: Mandatory server prefix for tool namespacing.
            spooler: SpoolerConfig to enable response spooling.
                If provided, the 4 spooler query tools are
                auto-registered.
            read_only: If True, tools with is_write_operation=True
                are silently skipped during registration.
            server_name: MCP server name. Defaults to the prefix.
        """
        self._prefix_resolver = PrefixResolver(prefix)
        self._registry = ToolRegistry(self._prefix_resolver)
        self._read_only = read_only
        self._server_name = server_name or prefix
        self._spooler: Optional[ResponseSpooler] = None
        self._spooler_config = spooler
        self._mcp_server: Any = None
        self._setup_done = False

    def register(self, tool: BaseTool) -> None:
        """Register a tool with the server.

        Write-operation tools are silently skipped if the server
        is in read-only mode.
        """
        if self._read_only and tool.is_write_operation:
            logger.debug(
                "Skipping write tool '%s' (read-only mode)", tool.name
            )
            return
        self._registry.register(tool)

    def register_all(self, tools: list[BaseTool]) -> None:
        """Register multiple tools at once."""
        for tool in tools:
            self.register(tool)

    async def _setup(self) -> None:
        """Async setup called once before the transport starts.

        Initialises the spooler (if configured), auto-registers
        internal tools, and creates the MCP SDK server with
        protocol handlers.
        """
        if self._setup_done:
            return

        # Initialise spooler if configured
        if self._spooler_config is not None:
            self._spooler = ResponseSpooler(self._spooler_config)
            await self._spooler.initialise()
            self._auto_register_spooler_tools()

        # Always register skills guide tools (last, so they see
        # all registered tools via the live registry reference)
        self._auto_register_skills_tools()

        # Create MCP SDK server and register handlers
        from mcp.server import Server

        self._mcp_server = Server(self._server_name)
        self._register_handlers()
        self._setup_done = True

    def _auto_register_spooler_tools(self) -> None:
        """Register the 4 spooler query tools."""
        from spindl.spooler.tools.aggregate import SpoolerAggregateTool
        from spindl.spooler.tools.distinct import SpoolerDistinctTool
        from spindl.spooler.tools.list_spools import SpoolerListSpoolsTool
        from spindl.spooler.tools.query import SpoolerQueryTool

        for tool_cls in [
            SpoolerListSpoolsTool,
            SpoolerQueryTool,
            SpoolerAggregateTool,
            SpoolerDistinctTool,
        ]:
            self._registry.register(tool_cls(spooler=self._spooler))

    def _auto_register_skills_tools(self) -> None:
        """Register the 2 skills guide tools."""
        from spindl.skills.describe_tool import DescribeToolTool
        from spindl.skills.list_tools import ListToolsTool

        self._registry.register(
            ListToolsTool(registry=self._registry)
        )
        self._registry.register(
            DescribeToolTool(registry=self._registry)
        )

    def _register_handlers(self) -> None:
        """Wire MCP protocol handlers to the SDK server."""
        from mcp.types import TextContent, Tool

        @self._mcp_server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return self._registry.get_mcp_tool_definitions()

        @self._mcp_server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict | None
        ) -> list[TextContent]:
            return await self._handle_call_tool(name, arguments)

    async def _handle_call_tool(
        self, name: str, arguments: dict | None
    ) -> list[Any]:
        """Dispatch a tool call by wire name."""
        from mcp.types import TextContent

        tool = self._registry.get_tool(name)
        if tool is None:
            error = StructuredError(
                error=ErrorDetail(
                    error_code="TOOL_NOT_FOUND",
                    error_message=f"No tool found with name '{name}'",
                    retry_eligible=False,
                    suggestion=(
                        "Check the tool name. Call the list_tools "
                        "tool to see available tools."
                    ),
                ),
            ).to_dict()
            return [
                TextContent(type="text", text=json.dumps(error))
            ]

        params = dict(arguments) if arguments else {}

        try:
            result = await tool.execute(**params)

            # Apply response spooling if tool opted in
            result = self._maybe_spool_response(tool, result)

            result_json = json.dumps(result, default=str)

            # Resolve @placeholders in the JSON output
            result_json = (
                self._prefix_resolver.resolve_placeholders(result_json)
            )

            return [TextContent(type="text", text=result_json)]

        except Exception as exc:
            logger.error(
                "Error executing tool '%s': %s", tool.name, exc
            )
            error = StructuredError(
                error=ErrorDetail(
                    error_code="EXECUTION_ERROR",
                    error_message=f"Tool execution failed: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
            return [
                TextContent(type="text", text=json.dumps(error))
            ]

    def _maybe_spool_response(
        self, tool: BaseTool, result: dict
    ) -> dict:
        """Apply response spooling if the tool has opted in."""
        if self._spooler is None:
            return result

        array_paths = getattr(tool, "spooler_array_paths", None)
        auto_detect = getattr(tool, "spooler_auto_detect", False)

        if array_paths is None and not auto_detect:
            return result

        # Only process successful responses with data
        if not result.get("success", False):
            return result

        data = result.get("data")
        if not isinstance(data, (dict, list)):
            return result

        try:
            processed = self._spooler.process_response(
                response=data,
                source_tool=tool.name,
                array_paths=array_paths,
            )
            if "spooled_data" in processed:
                result["data"] = processed
                # Update metadata with spooling guidance
                metadata = result.get("metadata", {})
                if isinstance(metadata, dict):
                    total_records = sum(
                        s["total_records"]
                        for s in processed["spooled_data"]
                    )
                    metadata["total_results"] = total_records
                    metadata["truncated"] = True
                    metadata["guidance"] = (
                        f"{total_records} records spooled. Use "
                        f"@spooler_query with spool_id to access."
                    )
                    result["metadata"] = metadata
        except Exception as exc:
            logger.warning(
                "Spooling failed for tool '%s', returning original "
                "response: %s",
                tool.name,
                exc,
            )

        return result

    async def run_stdio(self) -> None:
        """Run the server on stdio transport."""
        await self._setup()

        from mcp.server.stdio import stdio_server

        init_options = self._mcp_server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await self._mcp_server.run(
                read_stream, write_stream, init_options
            )

        await self._cleanup()

    async def run_http(
        self, host: str = "0.0.0.0", port: int = 8000
    ) -> None:
        """Run the server on HTTP streamable transport.

        Requires uvicorn (install with: pip install spindl[http]).
        Reads the X-Spindl-Prefix header for per-request instance
        prefixing.
        """
        await self._setup()

        try:
            import uvicorn
        except ImportError:
            raise ImportError(
                "uvicorn is required for HTTP transport. "
                "Install with: pip install spindl[http]"
            ) from None

        # Create the streamable HTTP app from MCP SDK
        from mcp.server.streamable_http import (
            StreamableHTTPServerTransport,
        )
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Route

        mcp_server = self._mcp_server
        prefix_resolver = self._prefix_resolver

        async def handle_mcp(request: Request) -> Response:
            # Extract instance prefix from header
            header_prefix = request.headers.get("x-spindl-prefix")
            if header_prefix:
                prefix_resolver.set_instance_prefix(header_prefix)
            else:
                prefix_resolver.set_instance_prefix(None)

            transport = StreamableHTTPServerTransport(
                "/mcp",
                is_json_response_enabled=True,
            )
            return await transport.handle_request(
                request, mcp_server
            )

        app = Starlette(routes=[Route("/mcp", handle_mcp, methods=["POST"])])

        config = uvicorn.Config(app, host=host, port=port)
        server = uvicorn.Server(config)
        await server.serve()
        await self._cleanup()

    async def run_sse(
        self, host: str = "0.0.0.0", port: int = 8000
    ) -> None:
        """Run the server on SSE transport.

        Requires uvicorn (install with: pip install spindl[http]).
        """
        await self._setup()

        try:
            import uvicorn
        except ImportError:
            raise ImportError(
                "uvicorn is required for SSE transport. "
                "Install with: pip install spindl[http]"
            ) from None

        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Route

        sse_transport = SseServerTransport("/messages/")
        mcp_server = self._mcp_server
        prefix_resolver = self._prefix_resolver

        async def handle_sse(request: Request) -> Response:
            header_prefix = request.headers.get("x-spindl-prefix")
            if header_prefix:
                prefix_resolver.set_instance_prefix(header_prefix)
            else:
                prefix_resolver.set_instance_prefix(None)

            return await sse_transport.handle_sse_connection(
                request, mcp_server
            )

        async def handle_messages(request: Request) -> Response:
            return await sse_transport.handle_post_message(
                request.scope, request.receive, request._send
            )

        app = Starlette(
            routes=[
                Route("/sse", handle_sse),
                Route("/messages/", handle_messages, methods=["POST"]),
            ]
        )

        config = uvicorn.Config(app, host=host, port=port)
        server = uvicorn.Server(config)
        await server.serve()
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        if self._spooler:
            await self._spooler.cleanup()
