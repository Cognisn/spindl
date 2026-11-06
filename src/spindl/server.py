"""MCP Server orchestrator for spindl.

Provides the top-level MCPServer class that wires together the
PrefixResolver, ToolRegistry, MCP SDK Server, and optional
ResponseSpooler. Supports stdio, HTTP streamable, and SSE transports.

Every ``tools/call`` passes three gates before tool code runs, in order:
tool access (the authenticator's ``authorise``), reach (refused when an
authenticator is configured, the tool requires reach and the credential
carries none) and argument checking. Tool access and reach are separate
controls: being allowed to call a tool never limits what it touches, so
the tool applies ``self.context.reach`` itself.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional

from spindl.auth import AuthConfig, Authenticator, Identity, ToolAction, ToolContext
from spindl.auth._context import (
    current_identity,
    reset_tool_context,
    set_tool_context,
)
from spindl.auth.adapters import TokenVerifierAuthenticator, ToolVisibilityAuthoriser
from spindl.prefix import PrefixResolver
from spindl.registry import ToolRegistry, ToolVisibility
from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.spooler.config import SpoolerConfig
from spindl.spooler.spooler import ResponseSpooler
from spindl.tool import BaseTool, ToolInputError

if TYPE_CHECKING:
    from mcp.server.context import ServerRequestContext
    from mcp.types import (
        CallToolRequestParams,
        CallToolResult,
        ListToolsResult,
        PaginatedRequestParams,
    )

    from spindl.wsgi import WsgiBridge

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
        tool_visibility: Optional[ToolVisibility] = None,
    ) -> None:
        """Initialise the MCP server.

        Args:
            prefix: Mandatory server prefix for tool namespacing.
            spooler: SpoolerConfig to enable response spooling.
                If provided, the 4 spooler query tools are
                auto-registered.
            server_name: MCP server name. Defaults to the prefix.
            auth: AuthConfig to require authentication on the HTTP and SSE
                transports. stdio is unaffected. With
                ``AuthConfig(authenticator=...)`` the authenticator decides
                tool access for ``tools/list``, ``tools/call`` and the skills
                guide tools alike, and every tool requires reach unless it
                sets ``requires_reach = False``.
            tool_visibility: Deprecated 0.4.0 per-request hook deciding
                whether a tool is visible to the caller. It is wrapped in an
                adapter with 0.4.0 behaviour exactly and logs one
                deprecation warning. Cannot be combined with an
                ``authenticator``; decide access in its ``authorise``.

        Raises:
            ValueError: ``tool_visibility`` given with an ``authenticator``.
        """
        if (
            tool_visibility is not None
            and auth is not None
            and auth.authenticator is not None
        ):
            raise ValueError(
                "MCPServer takes tool_visibility or an AuthConfig authenticator, "
                "not both. Decide tool access in the authenticator's authorise()."
            )
        if tool_visibility is not None:
            logger.warning(
                "MCPServer(tool_visibility=...) is deprecated and will be "
                "removed in a future release. Decide tool access in "
                "spindl.auth.Authenticator.authorise()."
            )
        self._prefix_resolver = PrefixResolver(prefix)
        self._registry = ToolRegistry(self._prefix_resolver)
        self._server_name = server_name or prefix
        self._auth = auth
        self._authenticator: Optional[Authenticator] = None
        self._legacy_access = False
        if auth is not None and auth.authenticator is not None:
            self._authenticator = auth.authenticator
        elif auth is not None and auth.token_verifier is not None:
            self._authenticator = TokenVerifierAuthenticator(
                auth.token_verifier, tool_visibility
            )
            self._legacy_access = True
        elif tool_visibility is not None:
            self._authenticator = ToolVisibilityAuthoriser(tool_visibility)
            self._legacy_access = True
        # Reach is required only when an Authenticator is configured
        # directly; the 0.4.0 adapters and no authentication leave it off.
        self._reach_required = (
            self._authenticator is not None and not self._legacy_access
        )
        if self._authenticator is not None:
            self._registry.set_access(self._check_access)
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
        self._registry.warn_undeclared_tools()

        # Create the MCP SDK server with its protocol handlers
        from mcp.server import Server

        self._mcp_server = Server(
            self._server_name,
            on_list_tools=self._on_list_tools,
            on_call_tool=self._on_call_tool,
        )
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

    @property
    def _step_up(self) -> bool:
        return self._auth is not None and self._auth.denial_mode == "step_up"

    async def _authorise(
        self, identity: Optional[Identity], tool: BaseTool, action: ToolAction
    ) -> bool:
        """Ask the authenticator whether ``identity`` may use ``tool``.

        Tool access only: the answer never limits what the tool touches.
        Fails closed: an authenticator that raises denies the tool.
        """
        authenticator: Any = self._authenticator
        if authenticator is None:
            return True
        if identity is None and not self._legacy_access:
            # No credential exists on this transport (stdio): there is no
            # identity to authorise. Reach still fails closed in the call
            # path, because there is no identity to carry it.
            return True
        try:
            return bool(await authenticator.authorise(identity, tool, action))
        except Exception as exc:
            logger.warning(
                "Authenticator authorise() raised %s for tool '%s'; denying it",
                type(exc).__name__,
                tool.name,
            )
            return False

    async def _check_access(self, tool: BaseTool, action: ToolAction) -> bool:
        """The registry's access check for the current request.

        In ``denial_mode = "step_up"`` a tool denied only for lack of
        permissions stays listed, so the client can see it and step up.
        """
        identity = current_identity()
        if await self._authorise(identity, tool, action):
            return True
        return action == "list" and bool(self._step_up_scopes(identity, tool))

    def _step_up_scopes(
        self, identity: Optional[Identity], tool: BaseTool
    ) -> list[str]:
        """Permissions ``tool`` declares that ``identity`` lacks, in step-up mode."""
        if not self._step_up or identity is None:
            return []
        return sorted(set(tool.permissions) - identity.tool_permissions)

    async def _call_gate(self, tool: Optional[BaseTool]) -> tuple[str, list[str]]:
        """Decide a call: ("allow", []), ("unknown", []) or ("step_up", missing)."""
        if tool is None:
            return "unknown", []
        if await self._registry.allows(tool, "call"):
            return "allow", []
        missing = self._step_up_scopes(current_identity(), tool)
        if missing:
            return "step_up", missing
        return "unknown", []

    def _reach_refusal(self, tool: BaseTool) -> Optional[dict[str, Any]]:
        """The structured refusal for a call lacking reach, or None to proceed."""
        if not self._reach_required or tool.requires_reach is False:
            return None
        identity = current_identity()
        if identity is not None and identity.reach is not None:
            return None
        return StructuredError(
            error=ErrorDetail(
                error_code="REACH_REQUIRED",
                error_message=(
                    f"Tool '{tool.name}' was not run: it requires reach (what a "
                    f"call may touch), and this credential carries none. Tool "
                    f"access was decided separately and does not grant reach."
                ),
                retry_eligible=False,
                suggestion=(
                    "Use a credential whose authenticator sets Identity.reach, "
                    "or, for a tool that touches nothing caller-specific, set "
                    "requires_reach = False on the tool class."
                ),
            ),
        ).to_dict()

    async def _step_up_gate(self, scope: Any, receive: Any, send: Any) -> Any:
        """Answer a ``tools/call`` needing more permissions with ``403``.

        Only in ``denial_mode = "step_up"``. Reads the request body, and when
        it is a call to a tool the caller lacks permissions for, answers
        ``403`` ``insufficient_scope`` naming them and returns None.
        Otherwise returns a ``receive`` that replays the body.
        """
        if not self._step_up or scope.get("method") != "POST":
            return receive
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        name = _called_tool_name(body)
        if name is not None:
            decision, missing = await self._call_gate(self._registry.lookup(name))
            if decision == "step_up":
                from spindl.auth.http import send_auth_error

                assert self._auth is not None
                await send_auth_error(
                    send,
                    self._auth,
                    403,
                    "insufficient_scope",
                    "The tool needs permissions this credential does not hold",
                    scope=missing,
                )
                return None
        replayed = False

        async def replay() -> Any:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return replay

    def _protect(self, app: Any) -> Any:
        """Wrap ``app`` in the authentication stack when auth is configured."""
        if self._auth is None:
            return app
        from spindl import auth as _auth

        return _auth.protect(app, self._auth, self._authenticator)

    def _metadata_routes(self) -> list[Any]:
        """The RFC 9728 metadata routes, or none when they are not served.

        ``scopes_supported`` adds every permission a registered tool
        declares to the configured scopes.
        """
        if self._auth is None or not self._auth.serve_metadata:
            return []
        from spindl import auth as _auth

        return _auth.metadata_routes(self._auth, self._registry.declared_permissions)

    async def _on_list_tools(  # NOSONAR - the SDK requires a coroutine
        self,
        ctx: "ServerRequestContext[Any]",
        params: "PaginatedRequestParams | None",
    ) -> "ListToolsResult":
        """Answer ``tools/list`` with the tools visible to this request."""
        from mcp.types import ListToolsResult

        return ListToolsResult(tools=await self._registry.tool_definitions())

    async def _on_call_tool(
        self,
        ctx: "ServerRequestContext[Any]",
        params: "CallToolRequestParams",
    ) -> "CallToolResult":
        """Answer ``tools/call`` by dispatching to the named tool."""
        from mcp.types import CallToolResult

        content = await self._handle_call_tool(params.name, params.arguments)
        return CallToolResult(content=content)

    async def _handle_call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> list[Any]:
        """Dispatch a tool call by wire name.

        Tool access is decided first (a denied tool is answered as unknown,
        or, in step-up mode, as lacking permissions), then reach, then the
        arguments; only then does tool code run.
        """
        from mcp.types import TextContent

        tool = self._registry.lookup(name)
        decision, missing = await self._call_gate(tool)
        if decision == "step_up":
            denied = StructuredError(
                error=ErrorDetail(
                    error_code="INSUFFICIENT_SCOPE",
                    error_message=(
                        f"Tool '{name}' needs permissions this credential does "
                        f"not hold: {' '.join(missing)}"
                    ),
                    retry_eligible=False,
                    suggestion=(
                        "Obtain a credential granting these permissions and "
                        "call the tool again."
                    ),
                ),
            ).to_dict()
            return [TextContent(type="text", text=json.dumps(denied))]
        if tool is None or decision != "allow":
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

        refusal = self._reach_refusal(tool)
        if refusal is not None:
            return [TextContent(type="text", text=json.dumps(refusal))]

        params = dict(arguments) if arguments else {}
        identity = current_identity()
        context_token = set_tool_context(
            ToolContext(
                identity=identity,
                reach=identity.reach if identity is not None else None,
                instance_prefix=self._prefix_resolver.instance_prefix,
            )
        )
        try:
            return await self._run_tool(tool, params)
        finally:
            reset_tool_context(context_token)

    async def _run_tool(self, tool: BaseTool, params: dict[str, Any]) -> list[Any]:
        """Check the arguments, execute the tool and render its result."""
        from mcp.types import TextContent

        try:
            # Reject arguments the tool never declared, rather than
            # dropping them silently and returning a result the caller
            # believes was constrained by them.
            tool.check_arguments(params)
            result = await tool.execute(**params)

            # Apply response spooling if tool opted in
            result = await self._maybe_spool_response(tool, result)

            result_json = json.dumps(result, default=str)

            # Resolve @placeholders in the JSON output
            result_json = self._prefix_resolver.resolve_placeholders(result_json)

            return [TextContent(type="text", text=result_json)]

        except ToolInputError as exc:
            logger.info("Rejected arguments for tool '%s': %s", tool.name, exc)
            return [TextContent(type="text", text=json.dumps(exc.to_dict()))]

        except Exception as exc:
            logger.exception("Error executing tool '%s': %s", tool.name, exc)
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
                "Spooling failed for tool '%s', returning original response: %s",
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
            gated = await self._step_up_gate(scope, receive, send)
            if gated is None:
                return
            await session_manager.handle_request(scope, gated, send)

        endpoint: Any = _AsgiEndpoint(handle_mcp)
        if self._auth is not None:
            endpoint = self._protect(handle_mcp)
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
        routes: list[Any] = self._metadata_routes()
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
            # The SDK runs each request in the context of the POST that
            # carried it, so the prefix is read from that POST as well.
            prefix_resolver.set_instance_prefix(_header(scope, "x-spindl-prefix"))
            gated = await self._step_up_gate(scope, receive, send)
            if gated is None:
                return
            await sse_transport.handle_post_message(scope, gated, send)

        routes: list[Any] = self._metadata_routes()
        sse_endpoint: Any = _AsgiEndpoint(handle_sse)
        messages_endpoint: Any = _AsgiEndpoint(handle_messages)
        if self._auth is not None:
            sse_endpoint = self._protect(handle_sse)
            messages_endpoint = self._protect(handle_messages)
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

    def wsgi_app(self) -> "WsgiBridge":
        """Return the HTTP streamable transport as a WSGI (PEP 3333) application.

        Mount it in any WSGI application, or on Flask with
        :func:`spindl.wsgi.init_app`. The bridge runs :meth:`http_endpoint`
        and :meth:`http_lifespan` on an event loop in a background thread it
        owns, so authentication, instance prefixing and tool visibility work
        exactly as on the ASGI endpoint. Responses are JSON; Server-Sent
        Events are not streamed. A server has one bridge: calling this again
        returns the same one, and after :meth:`WsgiBridge.close` it raises
        RuntimeError. Requires a2wsgi (install with:
        pip install cognisn-spindl[wsgi]).
        """
        from spindl.wsgi import bridge_for

        return bridge_for(self)


def _called_tool_name(body: bytes) -> Optional[str]:
    """The tool a JSON-RPC ``tools/call`` body names, or None for anything else."""
    try:
        message = json.loads(body)
    except ValueError:
        return None
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return None
    params = message.get("params")
    name = params.get("name") if isinstance(params, dict) else None
    return name if isinstance(name, str) else None


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
