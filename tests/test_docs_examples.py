"""Every Python example in README.md and docs/ runs here.

Each page's ```python blocks run in order in one namespace, as a reader
following the page would run them, so a later block may use what an earlier
one defined. Top-level ``await`` is allowed. A page may also carry hidden
blocks in HTML comments, which run in the same sequence:

    <!-- docs-test
    ...python...
    -->

Hidden blocks supply what a fragment assumes (a tool class, an existing
WSGI application) and check what an example claims (that a caller sees
only the collections in its reach, that a call is answered 403). They are
invisible on GitHub and PyPI.

``MCPServer.run_stdio``, ``run_http`` and ``run_sse`` are replaced while a
page runs: the replacement checks the call against the real signature and
returns, so an example can end with ``asyncio.run(server.run_http(...))``
without serving forever. Everything else is the real API, so an example
that drifts from it fails here.

Helpers available to hidden blocks:

* ``docs_client(server)``: an async context manager serving the server's
  HTTP app in process, with ``list(headers)``, ``call(name, arguments,
  headers)``, ``post(body, headers)`` and ``get(path)``.
* ``docs_log``: the warnings spindl logged while the page ran.
* ``docs_module(name, **attributes)``: registers a stand-in module, for an
  example that imports the reader's own package (``my_server.app``). It is
  removed when the page finishes.
"""

import ast
import asyncio
import inspect
import json
import logging
import re
import sys
import traceback
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

from spindl import MCPServer

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]

FENCE = re.compile(r"^(\s*)```(\S*)\s*$")
HIDDEN_OPEN = "<!-- docs-test"
HIDDEN_CLOSE = "-->"
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@dataclass
class Snippet:
    """One block of Python taken from a page."""

    page: Path
    line: int  # 1-based line of the first line of code
    source: str
    hidden: bool

    @property
    def where(self) -> str:
        return f"{self.page.relative_to(ROOT).as_posix()}:{self.line}"


def extract(page: Path) -> list[Snippet]:
    """The Python blocks of ``page``, visible and hidden, in page order."""
    lines = page.read_text(encoding="utf-8").splitlines()
    snippets: list[Snippet] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = FENCE.match(line)
        if line.strip() == HIDDEN_OPEN:
            end = _find(lines, i + 1, lambda text: text.strip() == HIDDEN_CLOSE)
            body = lines[i + 1 : end]
            snippets.append(Snippet(page, i + 2, "\n".join(body), hidden=True))
            i = end + 1
        elif fence is not None and fence.group(2):
            indent, language = fence.group(1), fence.group(2)
            end = _find(lines, i + 1, lambda text: text.strip() == "```")
            if language == "python":
                body = [text[len(indent) :] for text in lines[i + 1 : end]]
                snippets.append(Snippet(page, i + 2, "\n".join(body), hidden=False))
            i = end + 1
        else:
            i += 1
    return snippets


def _find(lines: list[str], start: int, test: Any) -> int:
    for index in range(start, len(lines)):
        if test(lines[index]):
            return index
    raise AssertionError(f"unterminated block starting near line {start}")


# ---------------------------------------------------------------------------
# Helpers offered to the hidden blocks
# ---------------------------------------------------------------------------


class DocsClient:
    """Requests to a server's HTTP app, served in process."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def post(
        self, body: dict[str, Any], headers: Optional[dict[str, str]] = None
    ) -> httpx.Response:
        return await self._client.post(
            "/mcp", json=body, headers={**JSON_HEADERS, **(headers or {})}
        )

    async def get(self, path: str) -> httpx.Response:
        return await self._client.get(path)

    async def list(self, headers: Optional[dict[str, str]] = None) -> list[Any]:
        """The tools/list entries this caller sees."""
        resp = await self.post(_rpc("tools/list", {}), headers)
        assert resp.status_code == 200, (resp.status_code, resp.text)
        tools: list[Any] = resp.json()["result"]["tools"]
        return tools

    async def call(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, Any]:
        """Call a tool; returns the HTTP status and the tool's JSON payload.

        For a non-200 answer the payload is the response body.
        """
        body = _rpc("tools/call", {"name": name, "arguments": arguments or {}})
        resp = await self.post(body, headers)
        if resp.status_code != 200:
            return resp.status_code, resp.json()
        return 200, json.loads(resp.json()["result"]["content"][0]["text"])


def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


@asynccontextmanager
async def docs_client(server: MCPServer) -> AsyncIterator[DocsClient]:
    # A session manager runs only once, so each client gets a fresh one.
    server._session_manager = None
    app = await server.build_http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield DocsClient(client)


class _Collect(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.WARNING)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(record.getMessage())


def _module_maker(added: list[str]) -> Any:
    def docs_module(name: str, **attributes: Any) -> types.ModuleType:
        parts = name.split(".")
        for depth in range(1, len(parts) + 1):
            dotted = ".".join(parts[:depth])
            if dotted not in sys.modules:
                module = types.ModuleType(dotted)
                module.__path__ = []
                sys.modules[dotted] = module
                added.append(dotted)
                if depth > 1:
                    parent = sys.modules[".".join(parts[: depth - 1])]
                    setattr(parent, parts[depth - 1], module)
        module = sys.modules[name]
        for key, value in attributes.items():
            setattr(module, key, value)
        return module

    return docs_module


def _fake_runner(name: str) -> Any:
    real = getattr(MCPServer, name)
    signature = inspect.signature(real)

    async def run(self: MCPServer, *args: Any, **kwargs: Any) -> None:
        # Refuse arguments the real method does not take, then return
        # instead of serving forever.
        signature.bind(self, *args, **kwargs)

    return run


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------


def run_snippet(snippet: Snippet, namespace: dict[str, Any]) -> None:
    # Pad with blank lines so tracebacks name the line in the page.
    source = "\n" * (snippet.line - 1) + snippet.source
    code = compile(
        source,
        str(snippet.page),
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        dont_inherit=True,
    )
    if code.co_flags & inspect.CO_COROUTINE:
        asyncio.run(eval(code, namespace))
    else:
        exec(code, namespace)


def _close_servers(namespace: dict[str, Any]) -> None:
    for value in list(namespace.values()):
        if isinstance(value, MCPServer):
            bridge = getattr(value, "_wsgi_bridge", None)
            if bridge is not None:
                bridge.close()


@pytest.mark.parametrize(
    "page", PAGES, ids=[p.relative_to(ROOT).as_posix() for p in PAGES]
)
def test_the_examples_on_the_page_run(page, monkeypatch, tmp_path):
    for name in ("run_stdio", "run_http", "run_sse"):
        monkeypatch.setattr(MCPServer, name, _fake_runner(name))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPINDL_INSTANCE_PREFIX", raising=False)
    # A spooler an example starts keeps its database in the test's folder.
    monkeypatch.setenv("SPOOLER_DB_PATH", str(tmp_path / "spooler.db"))
    log: list[str] = []
    handler = _Collect(log)
    spindl_logger = logging.getLogger("spindl")
    spindl_logger.addHandler(handler)
    added_modules: list[str] = []
    namespace: dict[str, Any] = {
        "__name__": f"docs_{page.stem.replace('-', '_')}",
        "docs_client": docs_client,
        "docs_log": log,
        "docs_module": _module_maker(added_modules),
    }
    try:
        for snippet in extract(page):
            try:
                run_snippet(snippet, namespace)
            except BaseException as exc:
                kind = "hidden check" if snippet.hidden else "example"
                raise AssertionError(
                    f"{kind} at {snippet.where} failed: {type(exc).__name__}: {exc}"
                ) from exc
    finally:
        _close_servers(namespace)
        spindl_logger.removeHandler(handler)
        for name in added_modules:
            sys.modules.pop(name, None)


@pytest.mark.parametrize(
    "page", PAGES, ids=[p.relative_to(ROOT).as_posix() for p in PAGES]
)
def test_every_python_block_is_collected(page):
    """No Python example escapes the runner under another fence label."""
    text = page.read_text(encoding="utf-8")
    labels = {m.group(2) for m in map(FENCE.match, text.splitlines()) if m}
    assert not labels & {"py", "python3", "pycon", "Python"}, labels
    fenced = sum(1 for line in text.splitlines() if line.strip() == "```python")
    visible = [s for s in extract(page) if not s.hidden]
    assert len(visible) == fenced


LINK = re.compile(r"\]\((?![a-z]+://)([^)#\s]+\.md)(#[^)\s]*)?\)")


def _anchors(page: Path) -> set[str]:
    anchors = set()
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
            anchors.add(slug)
    return anchors


@pytest.mark.parametrize(
    "page", PAGES, ids=[p.relative_to(ROOT).as_posix() for p in PAGES]
)
def test_links_between_pages_resolve(page):
    for match in LINK.finditer(page.read_text(encoding="utf-8")):
        target = (page.parent / match.group(1)).resolve()
        assert target.exists(), f"{page.name} links to missing {match.group(1)}"
        if match.group(2):
            anchor = match.group(2)[1:]
            assert anchor in _anchors(target), f"{page.name}: {match.group(0)}"


def test_the_runner_reports_the_line_of_a_broken_example(tmp_path, monkeypatch):
    page = tmp_path / "page.md"
    page.write_text(
        "Intro\n\n```python\nfrom spindl import MCPServer\n"
        "MCPServer(prefx='x')\n```\n",
        encoding="utf-8",
    )
    (snippet,) = extract(page)
    assert snippet.line == 4
    with pytest.raises(TypeError) as excinfo:
        run_snippet(snippet, {})
    frames = traceback.extract_tb(excinfo.value.__traceback__)
    assert [f.lineno for f in frames if f.filename == str(page)] == [5]
