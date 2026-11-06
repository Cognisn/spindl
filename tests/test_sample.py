"""The sample server runs, and answers real MCP clients over a real socket.

Each test starts ``sample/server.py`` as its own process, standalone over
HTTP streamable or mounted in its Flask application, with demo keys the
sample generates at start-up and writes to a file in the test's folder.
The tests then call tools with the ``mcp`` client and check the sample's
lessons: annotations on the wire, tool access by permission, reach applied
inside every tool, and 401 without a key.

Set SPINDL_TEST_SAMPLE_PORT to keep the listener inside a reserved block;
otherwise a free port is chosen.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import spindl

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample" / "server.py"
SAMPLE_PORT = int(os.environ.get("SPINDL_TEST_SAMPLE_PORT", "0"))
START_TIMEOUT = 45.0

READER_SITES = {"us-east-1", "eu-west-1"}


def free_port() -> int:
    if SAMPLE_PORT:
        return SAMPLE_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def child_env(tmp_path: Path) -> dict[str, str]:
    """Environment for the sample: this spindl checkout, a private spool file."""
    src = str(Path(spindl.__file__).resolve().parent.parent)
    existing = os.environ.get("PYTHONPATH")
    path = src if not existing else os.pathsep.join([src, existing])
    return {
        **os.environ,
        "PYTHONPATH": path,
        "SPOOLER_DB_PATH": str(tmp_path / "sample_spooler.db"),
        "PYTHONUNBUFFERED": "1",
    }


class RunningSample:
    def __init__(
        self, proc: "subprocess.Popen[bytes]", port: int, keys: dict[str, str]
    ):
        self.proc = proc
        self.base = f"http://127.0.0.1:{port}"
        self.keys = keys


def _drain(stream: Any, sink: list[str]) -> None:
    for raw in iter(stream.readline, b""):
        sink.append(raw.decode("utf-8", "replace"))


def _accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture
def start_sample(tmp_path: Path) -> Iterator[Any]:
    """Start the sample in a given mode; stop it when the test ends."""
    started: list["subprocess.Popen[bytes]"] = []
    output: list[str] = []

    def start(mode: str) -> RunningSample:
        port = free_port()
        keys_file = tmp_path / f"keys-{mode}.json"
        proc = subprocess.Popen(
            [
                sys.executable,
                str(SAMPLE),
                f"--{mode}",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--keys-file",
                str(keys_file),
            ],
            cwd=str(ROOT),
            env=child_env(tmp_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        started.append(proc)
        threading.Thread(target=_drain, args=(proc.stderr, output), daemon=True).start()
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"sample exited with {proc.returncode}:\n{''.join(output)}")
            if keys_file.exists() and _accepts(port):
                keys = json.loads(keys_file.read_text(encoding="utf-8"))
                return RunningSample(proc, port, keys)
            time.sleep(0.1)
        pytest.fail(f"sample did not start in {START_TIMEOUT}s:\n{''.join(output)}")

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


@asynccontextmanager
async def mcp_client(sample: RunningSample, key: str) -> AsyncIterator[Client]:
    async with httpx2.AsyncClient(
        headers={"X-API-Key": key}, timeout=30.0
    ) as http_client:
        transport = streamable_http_client(
            f"{sample.base}/mcp", http_client=http_client
        )
        async with Client(transport, cache=None) as client:
            yield client


def payload(result: Any) -> Any:
    return json.loads(result.content[0].text)


async def check_the_sample(sample: RunningSample) -> None:
    reader, editor = sample.keys["reader"], sample.keys["editor"]

    async with mcp_client(sample, reader) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        # Five devices fit inline; more would be spooled.
        devices = payload(await client.call_tool("inventory_get_devices", {"limit": 5}))
        vulns = payload(
            await client.call_tool("inventory_get_vulnerabilities", {"limit": 500})
        )

    # Tool access: the reader lacks inventory:write, so the write tool is hidden.
    assert "inventory_get_devices" in tools
    assert "inventory_acknowledge_finding" not in tools
    # Annotations on the wire.
    get_devices = tools["inventory_get_devices"]
    assert get_devices.title == "Get devices"
    assert get_devices.annotations is not None
    assert get_devices.annotations.read_only_hint is True
    assert get_devices.annotations.destructive_hint is False
    # Reach applied in the tool: only the reader's two sites.
    listed = devices["data"]["devices"]
    assert listed and {d["location"] for d in listed} == READER_SITES
    assert vulns["success"] is True

    async with mcp_client(sample, editor) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        everything = payload(
            await client.call_tool("inventory_get_devices", {"limit": 5})
        )
        acknowledged = payload(
            await client.call_tool(
                "inventory_acknowledge_finding", {"finding_id": "F-000"}
            )
        )
    assert "inventory_acknowledge_finding" in tools
    sites = {d["location"] for d in everything["data"]["devices"]}
    assert sites > READER_SITES
    assert acknowledged["data"] == {
        "finding_id": "F-000",
        "acknowledged_by": "editor@example.com",
    }

    async with httpx2.AsyncClient() as raw:
        anonymous = await raw.post(
            f"{sample.base}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert anonymous.status_code == 401
    assert "resource_metadata=" in anonymous.headers["WWW-Authenticate"]


async def test_the_sample_serves_http_streamable(start_sample):
    sample = start_sample("http")
    await check_the_sample(sample)


async def test_the_sample_serves_through_its_flask_app(start_sample):
    sample = start_sample("flask")
    await check_the_sample(sample)
    async with httpx2.AsyncClient() as raw:
        home = await raw.get(f"{sample.base}/")
        metadata = await raw.get(
            f"{sample.base}/.well-known/oauth-protected-resource/mcp"
        )
    assert home.status_code == 200 and "MCP endpoint" in home.text
    assert metadata.json()["scopes_supported"] == ["inventory:read", "inventory:write"]


def test_the_sample_keys_are_made_at_run_time():
    """No key is committed: the sample generates fresh ones at every start."""
    sys.path.insert(0, str(ROOT / "sample"))
    try:
        from server import build_server  # type: ignore[import-not-found]

        _, first = build_server("http://127.0.0.1:1/mcp")
        _, second = build_server("http://127.0.0.1:1/mcp")
        _, local = build_server()
    finally:
        sys.path.remove(str(ROOT / "sample"))
        for name in [
            n
            for n in sys.modules
            if n == "server" or n == "flask_app" or n.startswith("tools")
        ]:
            sys.modules.pop(name)
    assert set(first) == {"reader", "editor"}
    assert first["reader"] != second["reader"] and first["editor"] != second["editor"]
    assert local == {}
    committed = "".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "sample").rglob("*")
        if p.suffix in {".py", ".md"}
    )
    assert first["reader"] not in committed
