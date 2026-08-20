"""MCP Server orchestrator for spindl.

Provides the top-level MCPServer class that wires together the
PrefixResolver, ToolRegistry, MCP SDK Server, and optional
ResponseSpooler. Supports stdio, HTTP streamable, and SSE transports.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Optional

from spindl.auth import AuthConfig
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
        server_name: Optional[str] = None,
        auth: Optional[AuthConfig] = None,
    ) -> None:
        """Initialise the MCP server.

        Args:
            prefix: Mandatory server prefix for tool namespacing.
            spooler: SpoolerConfig to enable response spooling.
                If provided, the 4 spooler query tools are
                auto-registered.
            server_name: MCP server name. Defaults to the prefix.
            auth: AuthConfig to require bearer-token authentication on
                the HTTP and SSE transports. stdio is unaffected.
        """
        self._prefix_resolver = PrefixResolver(prefix)
        self._registry = ToolRegistry(self._prefix_resolver)
        self._server_name = server_name or prefix
        self._auth = auth
        self._spooler: Optional[ResponseSpooler] = None
        self._spooler_config = spooler
        self._mcp_server: Any = None
        self._session_manager: Any = None
        self._setup_done = False

    def register(self, tool: BaseTool) -> None:
        """Register a tool with the server."""
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
            await self._spooler.initialise_async()
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

        self._registry.register(ListToolsTool(registry=self._registry))
        self._registry.register(DescribeToolTool(registry=self._registry))

    def _register_handlers(self) -> None:
        """Wire MCP protocol handlers to the SDK server.

        The mcp SDK changed its low-level registration API in 2.0: 1.x
        exposes ``list_tools`` and ``call_tool`` decorators, 2.x exposes
        ``add_request_handler(method, params_type, handler)`` with a
        ``(ctx, params) -> result`` handler. Both are supported.
        """
        if hasattr(self._mcp_server, "add_request_handler"):
            self._register_handlers_v2()
        else:
            self._register_handlers_v1()

    def _register_handlers_v1(self) -> None:
        from mcp.types import TextContent, Tool

        @self._mcp_server.list_tools()  # type: ignore[untyped-decorator]
        async def handle_list_tools() -> list[Tool]:
            return self._registry.get_mcp_tool_definitions()

        @self._mcp_server.call_tool()  # type: ignore[untyped-decorator]
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[TextContent]:
            return await self._handle_call_tool(name, arguments)

    def _register_handlers_v2(self) -> None:
        from mcp import types

        async def handle_list_tools(  # NOSONAR(python:S7503) SDK requires a coroutine
            ctx: Any, params: Any
        ) -> types.ListToolsResult:
            return types.ListToolsResult(
                tools=self._registry.get_mcp_tool_definitions()
            )

        async def handle_call_tool(ctx: Any, params: Any) -> types.CallToolResult:
            content = await self._handle_call_tool(params.name, params.arguments)
            return types.CallToolResult(content=content)

        self._mcp_server.add_request_handler(
            "tools/list", types.PaginatedRequestParams, handle_list_tools
        )
        self._mcp_server.add_request_handler(
            "tools/call", types.CallToolRequestParams, handle_call_tool
        )

    async def _handle_call_tool(
        self, name: str, arguments: dict[str, Any] | None
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
            return [TextContent(type="text", text=json.dumps(error))]

        params = dict(arguments) if arguments else {}

        try:
            result = await tool.execute(**params)

            # Apply response spooling if tool opted in
            result = await self._maybe_spool_response(tool, result)

            result_json = json.dumps(result, default=str)

            # Resolve @placeholders in the JSON output
            result_json = self._prefix_resolver.resolve_placeholders(result_json)

            return [TextContent(type="text", text=result_json)]

        except Exception as exc:
            logger.error("Error executing tool '%s': %s", tool.name, exc)
            error = StructuredError(
                error=ErrorDetail(
                    error_code="EXECUTION_ERROR",
                    error_message=f"Tool execution failed: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
            return [TextContent(type="text", text=json.dumps(error))]

    async def _maybe_spool_response(
        self, tool: BaseTool, result: dict[str, Any]
    ) -> dict[str, Any]:
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
            processed = await self._spooler.process_response(
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
                        s["total_records"] for s in processed["spooled_data"]
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
                "Spooling failed for tool '%s', returning original " "response: %s",
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
            await self._mcp_server.run(read_stream, write_stream, init_options)

        await self._cleanup()

    async def http_endpoint(self) -> Any:
        """Return the HTTP streamable transport as a raw ASGI callable.

        Register it on your own router, for example
        ``Route("/mcp", await server.http_endpoint(), methods=["POST", "GET",
        "DELETE"])``, and run :meth:`http_lifespan` from your application's
        lifespan. When ``auth`` is configured the callable carries its own
        bearer-token stack, so no app-level middleware is needed. Reads the
        ``X-Spindl-Prefix`` header for per-request instance prefixing.
        """
        await self._setup()

        from mcp.server.streamable_http_manager import (
            StreamableHTTPSessionManager,
        )
        from starlette.types import Receive, Scope, Send

        if self._session_manager is None:
            self._session_manager = StreamableHTTPSessionManager(
                app=self._mcp_server,
                json_response=True,
                stateless=True,
            )
        session_manager = self._session_manager
        prefix_resolver = self._prefix_resolver

        async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
            prefix_resolver.set_instance_prefix(_header(scope, "x-spindl-prefix"))
            await session_manager.handle_request(scope, receive, send)

        endpoint: Any = _AsgiEndpoint(handle_mcp)
        if self._auth is not None:
            from spindl import auth as _auth

            endpoint = _auth.protect(handle_mcp, self._auth)
        return endpoint

    @asynccontextmanager
    async def http_lifespan(self, app: Any = None) -> AsyncIterator[None]:
        """Run the HTTP transport's session manager.

        Usable directly as a Starlette ``lifespan`` (it accepts and ignores
        the app argument) or nested inside your own lifespan. Requests to
        the endpoint from :meth:`http_endpoint` are only handled while this
        is running.
        """
        if self._session_manager is None:
            await self.http_endpoint()
        assert self._session_manager is not None
        async with self._session_manager.run():
            yield

    async def build_http_app(self, path: str = "/mcp") -> Any:
        """Build the Starlette application for the HTTP streamable transport.

        Serves the endpoint at ``path`` (stateless, JSON responses). Pass
        ``path="/"`` to serve at the application root so the app can be
        mounted under an external prefix. When ``auth`` is configured the
        endpoint requires a bearer token and, unless
        ``AuthConfig.serve_metadata`` is False, the RFC 9728
        protected-resource metadata document is served. The application's
        lifespan must be running for requests to be handled; ``run_http``
        does this through uvicorn.
        """
        from starlette.applications import Starlette
        from starlette.routing import Route

        endpoint = await self.http_endpoint()
        routes: list[Any] = []
        if self._auth is not None and self._auth.serve_metadata:
            from spindl import auth as _auth

            routes.extend(_auth.metadata_routes(self._auth))
        routes.append(Route(path, endpoint=endpoint, methods=["POST", "GET", "DELETE"]))
        return Starlette(routes=routes, lifespan=self.http_lifespan)

    async def build_sse_app(
        self, sse_path: str = "/sse", messages_path: str = "/messages/"
    ) -> Any:
        """Build the Starlette application for the SSE transport.

        Serves ``GET sse_path`` and ``POST messages_path``. When mounted
        under a prefix, the SDK transport prefixes the messages URL it
        advertises to clients with the mount path. When ``auth`` is
        configured both endpoints require a bearer token and, unless
        ``AuthConfig.serve_metadata`` is False, the metadata document is
        served.
        """
        await self._setup()

        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.types import Receive, Scope, Send

        sse_transport = SseServerTransport(messages_path)
        mcp_server = self._mcp_server
        prefix_resolver = self._prefix_resolver

        async def handle_sse(scope: Scope, receive: Receive, send: Send) -> None:
            prefix_resolver.set_instance_prefix(_header(scope, "x-spindl-prefix"))
            async with sse_transport.connect_sse(scope, receive, send) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )

        async def handle_messages(scope: Scope, receive: Receive, send: Send) -> None:
            await sse_transport.handle_post_message(scope, receive, send)

        routes: list[Any] = []
        sse_endpoint: Any = _AsgiEndpoint(handle_sse)
        messages_endpoint: Any = _AsgiEndpoint(handle_messages)
        if self._auth is not None:
            from spindl import auth as _auth

            sse_endpoint = _auth.protect(handle_sse, self._auth)
            messages_endpoint = _auth.protect(handle_messages, self._auth)
            if self._auth.serve_metadata:
                routes.extend(_auth.metadata_routes(self._auth))
        routes.append(Route(sse_path, endpoint=sse_endpoint, methods=["GET"]))
        routes.append(
            Route(messages_path, endpoint=messages_endpoint, methods=["POST"])
        )

        return Starlette(routes=routes)

    async def run_http(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Run the server on HTTP streamable transport.

        Requires uvicorn (install with: pip install spindl[http]).
        """
        app = await self.build_http_app()
        await self._serve(app, host, port)

    async def run_sse(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Run the server on SSE transport.

        Requires uvicorn (install with: pip install spindl[http]).
        """
        app = await self.build_sse_app()
        await self._serve(app, host, port)

    async def _serve(self, app: Any, host: str, port: int) -> None:
        try:
            import uvicorn
        except ImportError:
            raise ImportError(
                "uvicorn is required for HTTP and SSE transports. "
                "Install with: pip install spindl[http]"
            ) from None

        config = uvicorn.Config(app, host=host, port=port)
        server = uvicorn.Server(config)
        await server.serve()
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        if self._spooler:
            await self._spooler.cleanup_async()


def _header(scope: Any, name: str) -> Optional[str]:
    """Return a request header from an ASGI scope, or None."""
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode() or None
    return None


class _AsgiEndpoint:
    """Wrap a raw ASGI callable so Starlette routes it as an ASGI app.

    Starlette treats plain functions as request/response handlers; a
    callable object is passed the ASGI ``(scope, receive, send)`` triple.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self._app(scope, receive, send)
