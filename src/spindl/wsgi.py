"""Serve spindl's HTTP streamable transport from a WSGI application.

:meth:`spindl.server.MCPServer.wsgi_app` returns a :class:`WsgiBridge`, a
PEP 3333 application that runs spindl's ASGI endpoint inside any WSGI
server (Flask, Django, Werkzeug, gunicorn's sync and thread workers and so
on). :func:`init_app` mounts it on a Flask application.

Threading model: the bridge owns one background thread, named
``spindl-wsgi``, that runs an asyncio event loop. On that loop the bridge
enters :meth:`~spindl.server.MCPServer.http_lifespan` once, for the life of
the bridge, and runs the endpoint from
:meth:`~spindl.server.MCPServer.http_endpoint` for every request. Each WSGI
worker thread reads the request body, hands the request to the loop (the
ASGI scope is built with ``a2wsgi``) and blocks until the whole response is
ready, which it then returns to the WSGI server in one piece. The thread
starts on the first request or on :meth:`WsgiBridge.start`, and stops on
:meth:`WsgiBridge.close`, which also runs when the interpreter exits.

Responses are JSON. The bridge offers no Server-Sent Events stream: a
``GET`` on the endpoint is answered ``405``.

``a2wsgi`` comes with the ``wsgi`` extra (``pip install
cognisn-spindl[wsgi]``). Neither ``a2wsgi`` nor Flask is imported until it
is needed, so importing this module costs nothing when they are absent.
"""

import asyncio
import atexit
import concurrent.futures
import logging
import threading
import weakref
from collections.abc import Callable, Iterable
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from spindl.server import MCPServer

logger = logging.getLogger(__name__)

LOOP_THREAD_NAME = "spindl-wsgi"
INSTALL_HINT = (
    "The WSGI bridge needs a2wsgi. Install it with: pip install cognisn-spindl[wsgi]"
)
_CLOSED_MESSAGE = "the spindl WSGI bridge is closed"
_SERVER_ATTRIBUTE = "_wsgi_bridge"
_FLASK_EXTENSION = "spindl"
_READ_CHUNK = 65536
_CANCEL_WAIT = 2.0

Reply = tuple[int, list[tuple[str, str]], list[bytes]]

_create_lock = threading.Lock()
_open_lock = threading.Lock()
_open_bridges: "weakref.WeakSet[WsgiBridge]" = weakref.WeakSet()


def require_a2wsgi() -> Callable[[Any], Any]:
    """Return ``a2wsgi``'s WSGI-to-ASGI scope builder, or raise ImportError."""
    try:
        import a2wsgi  # noqa: F401  (the package itself must be importable)
        from a2wsgi.asgi import build_scope
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    return build_scope


class ClientDisconnected(OSError):
    """The client went away before sending the whole request body."""


def _read_body(environ: dict[str, Any]) -> bytes:
    """Read the whole request body, refusing one cut short by the client."""
    stream = environ.get("wsgi.input")
    if stream is None:
        return b""
    length = int(environ.get("CONTENT_LENGTH") or 0)
    if length <= 0:
        if environ.get("wsgi.input_terminated"):
            data: bytes = stream.read()
            return data
        return b""
    parts: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk: bytes = stream.read(min(remaining, _READ_CHUNK))
        if not chunk:
            raise ClientDisconnected(
                "client disconnected before sending the whole request body"
            )
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


class _Response:
    """A complete response collected from the ASGI application."""

    __slots__ = ("status", "headers", "body", "complete")

    def __init__(self) -> None:
        self.status: Optional[int] = None
        self.headers: list[tuple[str, str]] = []
        self.body: list[bytes] = []
        self.complete = asyncio.Event()


class WsgiBridge:
    """A PEP 3333 application serving an :class:`MCPServer` over HTTP.

    Obtain one with :meth:`MCPServer.wsgi_app`; a server has at most one
    bridge, so it never runs two session managers. The bridge serves the
    MCP endpoint at its mount point (an empty or ``/`` ``PATH_INFO``) and,
    when ``AuthConfig.serve_metadata`` is set, the RFC 9728 metadata
    document whenever a request's full path (``SCRIPT_NAME`` plus
    ``PATH_INFO``) is the document's path. The host routes that path to the
    bridge; :func:`init_app` does so for Flask.
    """

    def __init__(self, server: "MCPServer") -> None:
        self._build_scope = require_a2wsgi()
        self._server = server
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop: Optional[asyncio.Event] = None
        self._startup_error: Optional[BaseException] = None
        self._drain_timeout = 10.0
        self._running = False
        self._closed = False
        self._tasks: set["asyncio.Task[Any]"] = set()
        self._in_flight = 0
        self._in_flight_lock = threading.Lock()
        self._endpoint: Any = None
        self._metadata_route: Any = None
        self._metadata_path: Optional[str] = None
        with _open_lock:
            _open_bridges.add(self)

    # -- public API ---------------------------------------------------------

    @property
    def running(self) -> bool:
        """True while the loop thread is running the HTTP lifespan."""
        return self._running

    @property
    def closed(self) -> bool:
        """True once :meth:`close` has been called."""
        return self._closed

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """The bridge's event loop, or None before the thread starts."""
        return self._loop

    @property
    def active_requests(self) -> int:
        """Requests the bridge is handling now, from body read to response."""
        return self._in_flight

    def start(self) -> None:
        """Start the loop thread and the HTTP lifespan, if not yet running.

        Called automatically by the first request. Returns once the
        lifespan is running, so no request reaches the session manager
        before it is ready. Raises RuntimeError after :meth:`close` or if
        the lifespan fails to start.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError(_CLOSED_MESSAGE)
            if self._thread is not None:
                return
            loop = asyncio.new_event_loop()
            ready = threading.Event()
            thread = threading.Thread(
                target=self._run_loop,
                args=(loop, ready),
                name=LOOP_THREAD_NAME,
                daemon=False,
            )
            self._loop = loop
            self._thread = thread
            thread.start()
            ready.wait()
            if self._startup_error is not None:
                thread.join()
                self._closed = True
                self._thread = None
                raise RuntimeError(
                    "the spindl WSGI bridge failed to start its HTTP lifespan"
                ) from self._startup_error

    def close(self, timeout: float = 10.0) -> None:
        """Stop the HTTP lifespan and join the loop thread.

        Requests already in flight get up to ``timeout`` seconds to finish;
        any still running are then cancelled and answered ``503``. Safe to
        call more than once, and before the bridge has started. Afterwards
        the bridge refuses requests and :meth:`MCPServer.wsgi_app` refuses
        to make another, because a server's session manager runs only once.
        Also runs when the interpreter exits.
        """
        with self._lock:
            self._closed = True
            thread, loop, stop = self._thread, self._loop, self._stop
            self._thread = None
        if thread is None:
            return
        if thread is threading.current_thread():
            raise RuntimeError("close() cannot be called from the bridge's own loop")
        self._drain_timeout = timeout
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:  # pragma: no cover - loop already closed
                pass
        thread.join()

    def __call__(
        self, environ: dict[str, Any], start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        if self._closed:
            raise RuntimeError(_CLOSED_MESSAGE)
        self.start()
        loop = self._loop
        if loop is None:  # pragma: no cover - closed between the checks
            raise RuntimeError(_CLOSED_MESSAGE)
        with self._in_flight_lock:
            self._in_flight += 1
        try:
            body = _read_body(environ)
            scope = self._build_scope(environ)
            future = asyncio.run_coroutine_threadsafe(self._handle(scope, body), loop)
            try:
                status, headers, chunks = future.result()
            except concurrent.futures.CancelledError:
                status, headers, chunks = _plain(503, "the spindl WSGI bridge closed")
            except Exception:
                logger.exception("spindl WSGI bridge request failed")
                status, headers, chunks = _plain(500, "Internal Server Error")
        finally:
            with self._in_flight_lock:
                self._in_flight -= 1
        start_response(_status_line(status), headers)
        return chunks

    # -- the loop thread ----------------------------------------------------

    def _run_loop(
        self, loop: asyncio.AbstractEventLoop, ready: threading.Event
    ) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main(ready))
        except BaseException:  # pragma: no cover - logged, the thread must end
            logger.exception("spindl WSGI bridge loop failed")
        finally:
            try:
                _cancel_remaining(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                asyncio.set_event_loop(None)
                loop.close()
                ready.set()

    async def _main(self, ready: threading.Event) -> None:
        self._stop = asyncio.Event()
        try:
            await self._prepare()
            async with self._server.http_lifespan():
                self._running = True
                ready.set()
                await self._stop.wait()
                await self._drain()
        except BaseException as exc:
            if not ready.is_set():
                self._startup_error = exc
            else:
                logger.exception("spindl WSGI bridge lifespan failed")
        finally:
            self._running = False
            ready.set()
            try:
                await self._server._cleanup()
            except Exception:  # pragma: no cover - logged only
                logger.exception("spindl server clean-up failed")

    async def _prepare(self) -> None:
        self._endpoint = await self._server.http_endpoint()
        auth = self._server._auth
        if auth is not None and auth.serve_metadata:
            self._metadata_route = _metadata_route(auth)
            self._metadata_path = _metadata_path(auth)

    async def _drain(self) -> None:
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=self._drain_timeout)
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=_CANCEL_WAIT)

    # -- per request, on the loop -------------------------------------------

    async def _handle(self, scope: Any, body: bytes) -> Reply:
        """Run one request through the ASGI application and collect the reply."""
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        response = _Response()
        body_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await response.complete.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response.status = int(message["status"])
                response.headers = [
                    (name.decode("latin-1"), value.decode("latin-1"))
                    for name, value in message.get("headers", [])
                ]
            elif message["type"] == "http.response.body":
                response.body.append(bytes(message.get("body", b"")))
                if not message.get("more_body", False):
                    response.complete.set()

        try:
            await self._route(scope, receive, send)
        finally:
            response.complete.set()
            if task is not None:
                self._tasks.discard(task)
        if response.status is None:
            raise RuntimeError("the ASGI application sent no response")
        return response.status, response.headers, response.body

    async def _route(self, scope: Any, receive: Any, send: Any) -> None:
        from starlette.responses import PlainTextResponse

        path: str = scope.get("path", "")
        if self._metadata_route is not None and path == self._metadata_path:
            await self._metadata_route.handle(scope, receive, send)
            return
        root_path: str = scope.get("root_path", "")
        below = path[len(root_path) :] if path.startswith(root_path) else path
        if below not in ("", "/"):
            await PlainTextResponse("Not Found", 404)(scope, receive, send)
        elif scope.get("method") != "POST":
            # Responses are JSON only: no SSE stream is offered on GET.
            await PlainTextResponse(
                "Method Not Allowed", 405, headers={"Allow": "POST"}
            )(scope, receive, send)
        else:
            await self._endpoint(scope, receive, send)


def _metadata_route(auth: Any) -> Any:
    from spindl import auth as _auth

    return _auth.metadata_routes(auth)[0]


def _metadata_path(auth: Any) -> str:
    from urllib.parse import urlsplit

    from spindl import auth as _auth

    return urlsplit(_auth._metadata_url(auth)).path


def _plain(status: int, text: str) -> Reply:
    body = text.encode()
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    return status, headers, [body]


def _status_line(status: int) -> str:
    try:
        return f"{status} {HTTPStatus(status).phrase}"
    except ValueError:
        return f"{status} Unknown"


def _cancel_remaining(loop: asyncio.AbstractEventLoop) -> None:
    tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))


def _close_open_bridges() -> None:
    """Close every open bridge as the interpreter exits."""
    with _open_lock:
        bridges = list(_open_bridges)
    for bridge in bridges:
        try:
            bridge.close()
        except Exception:  # pragma: no cover - logged only
            logger.exception("closing the spindl WSGI bridge at exit failed")


# The loop thread is not a daemon thread. Python joins non-daemon threads
# before it runs atexit hooks, so an atexit hook alone would never be
# reached and the interpreter would hang on exit. The same hook is
# therefore registered with threading's exit hooks too, which run before
# that join (concurrent.futures relies on the same mechanism).
atexit.register(_close_open_bridges)
_threading_atexit = getattr(threading, "_register_atexit", None)
if _threading_atexit is not None:
    _threading_atexit(_close_open_bridges)


def bridge_for(server: "MCPServer") -> WsgiBridge:
    """Return the server's one bridge, creating it on first use.

    Raises RuntimeError once that bridge is closed, because the server's
    session manager cannot run a second time.
    """
    require_a2wsgi()
    with _create_lock:
        bridge: Optional[WsgiBridge] = getattr(server, _SERVER_ATTRIBUTE, None)
        if bridge is None:
            bridge = WsgiBridge(server)
            setattr(server, _SERVER_ATTRIBUTE, bridge)
        elif bridge.closed:
            raise RuntimeError(
                "this server's WSGI bridge is closed; its session manager "
                "cannot be started again"
            )
        return bridge


def init_app(app: Any, server: "MCPServer", path: str = "/mcp") -> WsgiBridge:
    """Mount ``server`` on a Flask application at ``path``.

    Wraps ``app.wsgi_app`` in Werkzeug's ``DispatcherMiddleware`` so that
    requests under ``path`` go to the server's :class:`WsgiBridge` and all
    others reach the Flask application as before. When the server's
    ``AuthConfig.serve_metadata`` is set, the RFC 9728 metadata path is
    mounted on the bridge too. Refuses a second registration on the same
    app. Werkzeug is imported only when this is called. Returns the bridge.
    """
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    extensions: dict[str, Any] = app.extensions
    if _FLASK_EXTENSION in extensions:
        raise RuntimeError("a spindl server is already registered on this app")
    mount = path.rstrip("/")
    if not mount.startswith("/"):
        raise ValueError("path must start with '/' and name a sub-path, like '/mcp'")
    bridge = server.wsgi_app()
    mounts: dict[str, Any] = {mount: bridge}
    auth = server._auth
    if auth is not None and auth.serve_metadata:
        mounts[_metadata_path(auth)] = bridge
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, mounts)
    extensions[_FLASK_EXTENSION] = bridge
    return bridge
