"""Tests for the WSGI bridge: spindl's HTTP endpoint inside a WSGI application.

Covers ``MCPServer.wsgi_app()`` called directly as a plain PEP 3333
application, the Flask helper ``spindl.wsgi.init_app`` exercised through
Flask's test client and through a real Werkzeug server on 127.0.0.1, the
bridge's background event loop and its lifecycle, authentication through the
bridge, the instance prefix header, and the optional ``wsgi`` extra.
"""

import asyncio
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from wsgiref.util import setup_testing_defaults

import pytest
from flask import Flask
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel
from werkzeug.serving import make_server as make_werkzeug_server

from spindl.auth import AuthConfig, current_identity
from spindl.server import MCPServer
from spindl.tool import BaseTool
from spindl.wsgi import WsgiBridge, init_app

ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "example-client", "version": "1"},
}
MODERN_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2026-07-28",
}
RESOURCE_URL = "http://localhost/mcp"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
AUTH_SERVER_URL = "https://auth.example.com/"
# The real-server tests need a socket. Port 0 asks the OS for a free one; set
# SPINDL_TEST_WSGI_PORT to keep the listener inside a reserved block.
TEST_PORT = int(os.environ.get("SPINDL_TEST_WSGI_PORT", "0"))
LOOP_THREAD = "spindl-wsgi"


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo the given text"
    category = "general"

    class InputModel(BaseModel):
        text: str = "hello"

    def guide(self) -> str:
        return "Call @echo."

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {"text": params.get("text", "hello")}}


class SlowTool(BaseTool):
    """Sleeps, recording how many calls were running at once."""

    name = "slow"
    description = "Sleep briefly and echo"
    category = "general"
    running = 0
    peak = 0

    class InputModel(BaseModel):
        text: str = "slow"
        seconds: float = 0.3

    def guide(self) -> str:
        return "Call @slow."

    async def execute(self, **params: Any) -> dict[str, Any]:
        cls = type(self)
        cls.running += 1
        cls.peak = max(cls.peak, cls.running)
        try:
            await asyncio.sleep(params.get("seconds", 0.3))
        finally:
            cls.running -= 1
        return {"success": True, "data": {"text": params.get("text", "slow")}}


class WhoAmITool(BaseTool):
    name = "whoami"
    description = "Return the authenticated caller"
    category = "diagnostics"

    def guide(self) -> str:
        return "Call @whoami."

    async def execute(self, **params: Any) -> dict[str, Any]:
        identity = current_identity()
        return {"subject": identity.subject if identity else None}


class StaticVerifier:
    """Token verifier that accepts a fixed set of tokens."""

    def __init__(self) -> None:
        self.tokens = {
            "good-token": AccessToken(
                token="good-token",
                client_id="client-a",
                scopes=["read", "write"],
                subject="user-1",
            ),
            "weak-token": AccessToken(
                token="weak-token",
                client_id="client-b",
                scopes=["read"],
                subject="user-2",
            ),
        }

    async def verify_token(self, token: str) -> AccessToken | None:
        return self.tokens.get(token)


def make_auth(required_scopes: list[str] | None = None) -> AuthConfig:
    return AuthConfig(
        token_verifier=StaticVerifier(),
        resource_server_url=RESOURCE_URL,
        authorization_servers=[AUTH_SERVER_URL],
        required_scopes=required_scopes if required_scopes is not None else ["read"],
    )


def make_server(auth: AuthConfig | None = None) -> MCPServer:
    server = MCPServer(prefix="test", auth=auth)
    server.register(EchoTool())
    server.register(SlowTool())
    server.register(WhoAmITool())
    return server


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {**(params or {}), "_meta": dict(ENVELOPE)},
    }


def rpc_headers(method: str, name: str | None = None, **extra: str) -> dict[str, str]:
    headers = {**MODERN_HEADERS, "Mcp-Method": method, **extra}
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def tool_text(body: dict[str, Any]) -> Any:
    return json.loads(body["result"]["content"][0]["text"])


def make_flask_app(server: MCPServer) -> Flask:
    app = Flask("wsgi-host")

    @app.get("/")
    def index() -> str:
        return "host index"

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    init_app(app, server)
    return app


def bridge_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == LOOP_THREAD]


def wait_for(predicate: Callable[[], bool], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@pytest.fixture
def server() -> Iterator[MCPServer]:
    srv = make_server()
    yield srv
    bridge = getattr(srv, "_wsgi_bridge", None)
    if bridge is not None:
        bridge.close()


@pytest.fixture
def auth_server() -> Iterator[MCPServer]:
    srv = make_server(make_auth())
    yield srv
    bridge = getattr(srv, "_wsgi_bridge", None)
    if bridge is not None:
        bridge.close()


@pytest.fixture(autouse=True)
def no_bridge_thread_left_behind() -> Iterator[None]:
    yield
    assert wait_for(lambda: not bridge_threads(), timeout=10.0), bridge_threads()


# ---------------------------------------------------------------------------
# A plain PEP 3333 caller, no Flask or Werkzeug involved.
# ---------------------------------------------------------------------------


def call_wsgi(
    app: Callable[..., Any],
    method: str = "POST",
    path: str = "",
    script_name: str = "/mcp",
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str], bytes]:
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": script_name,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    for key, value in (headers or {}).items():
        name = key.upper().replace("-", "_")
        if name == "CONTENT_TYPE":
            environ["CONTENT_TYPE"] = value
        else:
            environ["HTTP_" + name] = value
    setup_testing_defaults(environ)
    captured: dict[str, Any] = {}

    def start_response(status: str, response_headers: list[Any], exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(response_headers)
        return lambda data: None

    result = app(environ, start_response)
    try:
        payload = b"".join(result)
    finally:
        close = getattr(result, "close", None)
        if close is not None:
            close()
    return captured["status"], captured["headers"], payload


def plain_host(bridge: Callable[..., Any]) -> Callable[..., Any]:
    """A hand-written WSGI host that mounts the bridge at /mcp."""

    def app(environ: dict[str, Any], start_response: Any) -> Any:
        path = environ.get("PATH_INFO", "")
        if path == "/mcp" or path.startswith("/mcp/"):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + "/mcp"
            environ["PATH_INFO"] = path[len("/mcp") :]
            return bridge(environ, start_response)
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"plain host"]

    return app


class TestPlainWsgi:
    def test_wsgi_app_returns_a_pep_3333_callable(self, server):
        bridge = server.wsgi_app()
        assert isinstance(bridge, WsgiBridge)
        status, headers, body = call_wsgi(
            bridge,
            body=json.dumps(rpc("tools/list")).encode(),
            headers=rpc_headers("tools/list"),
        )
        assert status.startswith("200")
        assert headers["content-type"].startswith("application/json")
        names = {tool["name"] for tool in json.loads(body)["result"]["tools"]}
        assert {"test_echo", "test_slow"} <= names

    def test_mounted_in_a_hand_written_host(self, server):
        host = plain_host(server.wsgi_app())
        status, _, body = call_wsgi(host, method="GET", script_name="", path="/")
        assert status.startswith("200") and body == b"plain host"
        status, _, body = call_wsgi(
            host,
            script_name="",
            path="/mcp",
            body=json.dumps(
                rpc("tools/call", {"name": "test_echo", "arguments": {"text": "hi"}})
            ).encode(),
            headers=rpc_headers("tools/call", "test_echo"),
        )
        assert status.startswith("200")
        assert tool_text(json.loads(body)) == {"success": True, "data": {"text": "hi"}}

    def test_paths_below_the_mount_point_are_not_found(self, server):
        status, _, _ = call_wsgi(
            server.wsgi_app(),
            path="/elsewhere",
            body=json.dumps(rpc("tools/list")).encode(),
            headers=rpc_headers("tools/list"),
        )
        assert status.startswith("404")

    def test_get_offers_no_event_stream(self, server):
        status, headers, _ = call_wsgi(
            server.wsgi_app(), method="GET", headers={"Accept": "text/event-stream"}
        )
        assert status.startswith("405")
        assert headers["allow"] == "POST"

    def test_responses_are_complete_with_no_request_left_running(self, server):
        bridge = server.wsgi_app()
        for _ in range(3):
            call_wsgi(
                bridge,
                body=json.dumps(rpc("tools/list")).encode(),
                headers=rpc_headers("tools/list"),
            )
        assert bridge.active_requests == 0
        assert not bridge._tasks


# ---------------------------------------------------------------------------
# Flask, through its test client.
# ---------------------------------------------------------------------------


class TestFlaskTestClient:
    def test_server_discover(self, server):
        client = make_flask_app(server).test_client()
        resp = client.post(
            "/mcp", json=rpc("server/discover"), headers=rpc_headers("server/discover")
        )
        assert resp.status_code == 200
        result = resp.get_json()["result"]
        assert "2026-07-28" in result["supportedVersions"]
        assert "tools" in result["capabilities"]

    def test_handshake_era_initialise(self, server):
        client = make_flask_app(server).test_client()
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "example-client", "version": "1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["result"]["serverInfo"]["name"] == "test"

    def test_tools_list_and_tools_call(self, server):
        client = make_flask_app(server).test_client()
        listed = client.post(
            "/mcp", json=rpc("tools/list"), headers=rpc_headers("tools/list")
        )
        called = client.post(
            "/mcp",
            json=rpc("tools/call", {"name": "test_echo", "arguments": {"text": "hi"}}),
            headers=rpc_headers("tools/call", "test_echo"),
        )
        names = {tool["name"] for tool in listed.get_json()["result"]["tools"]}
        assert {"test_echo", "test_slow", "test_list_tools"} <= names
        assert tool_text(called.get_json()) == {
            "success": True,
            "data": {"text": "hi"},
        }

    def test_instance_prefix_header_passes_through(self, server):
        client = make_flask_app(server).test_client()
        listed = client.post(
            "/mcp",
            json=rpc("tools/list"),
            headers=rpc_headers("tools/list", **{"X-Spindl-Prefix": "prod"}),
        )
        called = client.post(
            "/mcp",
            json=rpc("tools/call", {"name": "prod_test_echo", "arguments": {}}),
            headers=rpc_headers(
                "tools/call", "prod_test_echo", **{"X-Spindl-Prefix": "prod"}
            ),
        )
        names = {tool["name"] for tool in listed.get_json()["result"]["tools"]}
        assert "prod_test_echo" in names and "test_echo" not in names
        assert tool_text(called.get_json())["success"] is True

    def test_ordinary_flask_routes_are_unaffected(self, server):
        client = make_flask_app(server).test_client()
        assert client.get("/").get_data() == b"host index"
        assert client.get("/health").get_json() == {"status": "ok"}
        assert client.get("/missing").status_code == 404

    def test_init_app_refuses_a_second_registration(self, server):
        app = make_flask_app(server)
        with pytest.raises(RuntimeError, match="already registered"):
            init_app(app, server)

    def test_init_app_honours_a_custom_path(self, server):
        app = Flask("custom-path")
        init_app(app, server, path="/tools/mcp")
        resp = app.test_client().post(
            "/tools/mcp", json=rpc("tools/list"), headers=rpc_headers("tools/list")
        )
        assert resp.status_code == 200


class TestAuthentication:
    def test_missing_token_is_challenged_through_the_bridge(self, auth_server):
        client = make_flask_app(auth_server).test_client()
        resp = client.post(
            "/mcp", json=rpc("tools/list"), headers=rpc_headers("tools/list")
        )
        assert resp.status_code == 401
        challenge = resp.headers["WWW-Authenticate"]
        assert challenge.startswith("Bearer")
        assert f'resource_metadata="http://localhost{METADATA_PATH}"' in challenge

    def test_valid_token_reaches_the_tool(self, auth_server):
        client = make_flask_app(auth_server).test_client()
        resp = client.post(
            "/mcp",
            json=rpc("tools/call", {"name": "test_whoami", "arguments": {}}),
            headers=rpc_headers(
                "tools/call", "test_whoami", Authorization="Bearer good-token"
            ),
        )
        assert resp.status_code == 200
        assert tool_text(resp.get_json()) == {"subject": "user-1"}

    def test_missing_scope_is_forbidden_with_a_challenge(self):
        srv = make_server(make_auth(["write"]))
        try:
            client = make_flask_app(srv).test_client()
            resp = client.post(
                "/mcp",
                json=rpc("tools/list"),
                headers=rpc_headers("tools/list", Authorization="Bearer weak-token"),
            )
        finally:
            srv.wsgi_app().close()
        assert resp.status_code == 403
        assert 'error="insufficient_scope"' in resp.headers["WWW-Authenticate"]

    def test_authentication_off_needs_no_token(self, server):
        client = make_flask_app(server).test_client()
        resp = client.post(
            "/mcp",
            json=rpc("tools/call", {"name": "test_whoami", "arguments": {}}),
            headers=rpc_headers("tools/call", "test_whoami"),
        )
        assert resp.status_code == 200
        assert tool_text(resp.get_json()) == {"subject": None}

    def test_init_app_serves_the_metadata_document(self, auth_server):
        client = make_flask_app(auth_server).test_client()
        resp = client.get(METADATA_PATH)
        assert resp.status_code == 200
        document = resp.get_json()
        assert document["resource"] == RESOURCE_URL
        assert document["authorization_servers"] == [AUTH_SERVER_URL]

    def test_metadata_not_served_when_disabled(self):
        auth = make_auth()
        auth.serve_metadata = False
        srv = make_server(auth)
        try:
            client = make_flask_app(srv).test_client()
            assert client.get(METADATA_PATH).status_code == 404
        finally:
            srv.wsgi_app().close()

    def test_bridge_serves_metadata_when_the_host_routes_it(self, auth_server):
        bridge = auth_server.wsgi_app()
        status, _, body = call_wsgi(
            bridge, method="GET", script_name=METADATA_PATH, path=""
        )
        assert status.startswith("200")
        assert json.loads(body)["resource"] == RESOURCE_URL


# ---------------------------------------------------------------------------
# The bridge's loop thread and lifecycle.
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_lifespan_runs_before_the_first_request(self, server):
        bridge = server.wsgi_app()
        assert not bridge.running and not bridge_threads()
        status, _, _ = call_wsgi(
            bridge,
            body=json.dumps(rpc("tools/list")).encode(),
            headers=rpc_headers("tools/list"),
        )
        assert status.startswith("200")
        assert bridge.running

    def test_explicit_start_runs_one_non_daemon_thread(self, server):
        bridge = server.wsgi_app()
        bridge.start()
        bridge.start()
        threads = bridge_threads()
        assert len(threads) == 1
        assert not threads[0].daemon
        assert bridge.running

    def test_wsgi_app_reuses_the_bridge(self, server):
        first = server.wsgi_app()
        first.start()
        manager = server._session_manager
        second = server.wsgi_app()
        second.start()
        assert second is first
        assert server._session_manager is manager
        assert len(bridge_threads()) == 1

    def test_close_stops_the_lifespan_and_joins_the_thread(self, server):
        bridge = server.wsgi_app()
        bridge.start()
        loop = bridge.loop
        assert loop is not None and loop.is_running()
        bridge.close()
        assert not bridge.running
        assert not bridge_threads()
        assert loop.is_closed()

    def test_close_is_idempotent_and_safe_before_start(self, server):
        bridge = server.wsgi_app()
        bridge.close()
        bridge.close()
        assert not bridge_threads()

    def test_calling_the_bridge_after_close_raises(self, server):
        bridge = server.wsgi_app()
        bridge.start()
        bridge.close()
        with pytest.raises(RuntimeError, match="closed"):
            call_wsgi(bridge, body=b"{}", headers=rpc_headers("tools/list"))
        with pytest.raises(RuntimeError, match="closed"):
            bridge.start()

    def test_wsgi_app_after_close_refuses(self, server):
        server.wsgi_app().close()
        with pytest.raises(RuntimeError, match="closed"):
            server.wsgi_app()

    def test_interpreter_exit_closes_an_open_bridge(self, tmp_path):
        script = tmp_path / "exit_without_close.py"
        script.write_text(
            textwrap.dedent("""
                from spindl.server import MCPServer

                server = MCPServer(prefix="exit")
                bridge = server.wsgi_app()
                bridge.start()
                assert bridge.running
                print("started", flush=True)
                """),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert "started" in proc.stdout


class TestOptionalDependencies:
    def test_wsgi_app_names_the_extra_when_a2wsgi_is_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "a2wsgi", None)
        srv = make_server()
        with pytest.raises(ImportError, match=r"pip install cognisn-spindl\[wsgi\]"):
            srv.wsgi_app()

    def test_spindl_imports_without_flask_or_a2wsgi(self):
        code = textwrap.dedent("""
            import sys
            for name in ("a2wsgi", "flask", "werkzeug"):
                sys.modules[name] = None
            import spindl
            import spindl.server
            import spindl.wsgi
            from spindl import MCPServer
            MCPServer(prefix="bare")
            loaded = [m for m in ("flask", "werkzeug", "a2wsgi")
                      if sys.modules.get(m) is not None]
            print("ok", loaded)
            """)
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "ok []"

    def test_importing_spindl_wsgi_loads_neither_flask_nor_a2wsgi(self):
        code = (
            "import sys, spindl.wsgi; "
            "print(sorted(m for m in ('flask', 'werkzeug', 'a2wsgi') "
            "if m in sys.modules))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "[]"


# ---------------------------------------------------------------------------
# A real Werkzeug server on 127.0.0.1.
# ---------------------------------------------------------------------------


@contextmanager
def running_werkzeug(app: Any) -> Iterator[int]:
    srv = make_werkzeug_server("127.0.0.1", TEST_PORT, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, name="test-werkzeug")
    thread.start()
    try:
        yield srv.server_port
    finally:
        srv.shutdown()
        thread.join(timeout=30)
        srv.server_close()


def post(
    port: int, body: dict[str, Any], headers: dict[str, str], path: str = "/mcp"
) -> tuple[int, Any, Any]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("POST", path, body=json.dumps(body), headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, resp.headers, json.loads(data)
    finally:
        conn.close()


class TestRealServer:
    def test_tools_list_and_call(self, server):
        with running_werkzeug(make_flask_app(server)) as port:
            status, _, listed = post(port, rpc("tools/list"), rpc_headers("tools/list"))
            _, _, called = post(
                port,
                rpc("tools/call", {"name": "test_echo", "arguments": {"text": "x"}}),
                rpc_headers("tools/call", "test_echo"),
            )
        assert status == 200
        assert "test_echo" in {tool["name"] for tool in listed["result"]["tools"]}
        assert tool_text(called) == {"success": True, "data": {"text": "x"}}

    def test_authentication_challenge_over_the_wire(self, auth_server):
        with running_werkzeug(make_flask_app(auth_server)) as port:
            status, headers, _ = post(
                port, rpc("tools/list"), rpc_headers("tools/list")
            )
        assert status == 401
        assert "resource_metadata=" in headers["WWW-Authenticate"]

    def test_concurrent_requests_from_several_threads(self, server):
        SlowTool.running = SlowTool.peak = 0
        results: dict[int, Any] = {}
        errors: list[BaseException] = []

        def worker(index: int, port: int) -> None:
            prefix = f"inst{index}"
            name = f"{prefix}_test_slow"
            try:
                results[index] = post(
                    port,
                    rpc("tools/call", {"name": name, "arguments": {"text": prefix}}),
                    rpc_headers("tools/call", name, **{"X-Spindl-Prefix": prefix}),
                )
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        with running_werkzeug(make_flask_app(server)) as port:
            workers = [
                threading.Thread(target=worker, args=(i, port)) for i in range(8)
            ]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join(timeout=60)
        assert not errors
        assert len(results) == 8
        for index, (status, _, body) in results.items():
            assert status == 200
            assert tool_text(body) == {
                "success": True,
                "data": {"text": f"inst{index}"},
            }
        assert SlowTool.peak > 1

    def test_client_disconnect_while_sending_the_body(self, server):
        bridge = server.wsgi_app()
        with running_werkzeug(make_flask_app(server)) as port:
            post(port, rpc("tools/list"), rpc_headers("tools/list"))
            with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
                sock.sendall(
                    b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Accept: application/json, text/event-stream\r\n"
                    b"Content-Length: 4000\r\n\r\n"
                    b'{"jsonrpc": "2.0", "id": 1,'
                )
                assert wait_for(lambda: bridge.active_requests == 1, timeout=10)
            assert wait_for(lambda: bridge.active_requests == 0)
            status, _, _ = post(port, rpc("tools/list"), rpc_headers("tools/list"))
        assert status == 200

    def test_client_disconnect_while_a_tool_runs(self, server):
        bridge = server.wsgi_app()
        body = json.dumps(
            rpc("tools/call", {"name": "test_slow", "arguments": {"seconds": 0.5}})
        ).encode()
        headers = "".join(
            f"{k}: {v}\r\n" for k, v in rpc_headers("tools/call", "test_slow").items()
        )
        with running_werkzeug(make_flask_app(server)) as port:
            with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
                sock.sendall(
                    b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    + headers.encode()
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body
                )
                assert wait_for(lambda: bridge.active_requests == 1, timeout=10)
            assert wait_for(lambda: bridge.active_requests == 0)
            status, _, _ = post(port, rpc("tools/list"), rpc_headers("tools/list"))
        assert status == 200

    def test_close_leaves_no_thread_or_loop_running(self, server):
        bridge = server.wsgi_app()
        with running_werkzeug(make_flask_app(server)) as port:
            post(port, rpc("tools/list"), rpc_headers("tools/list"))
        loop = bridge.loop
        bridge.close()
        assert not bridge_threads()
        assert loop is not None and loop.is_closed()
