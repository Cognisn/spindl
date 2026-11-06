# Transports

Spindl serves the same tools over stdio, HTTP streamable and SSE, and can
serve HTTP streamable from inside a WSGI application. Your tools don't
change; only the `run_*()` method, or the application you mount, differs.

Spindl requires the `mcp` SDK 2.3 or later (below 3.0) and speaks MCP protocol revision 2026-07-28 on every transport, while still answering clients that use the earlier `initialize` handshake.

<!-- docs-test
import asyncio
from typing import Any

from spindl import BaseTool, MCPServer


class MyTool(BaseTool):
    name = "ping"
    description = "Health check"
    category = "meta"
    read_only = True
    destructive = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": "pong"}


server = MCPServer(prefix="secops")
server.register(MyTool())
-->

## stdio

Standard I/O transport. The server reads from stdin and writes to stdout.

```python
asyncio.run(server.run_stdio())
```

**Use when:**
- Connecting to local MCP clients (Claude Desktop, Cursor, VS Code, JetBrains)
- Running as a subprocess spawned by the client
- Single-client scenarios

**Configuration in Claude Desktop (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "secops": {
      "command": "python",
      "args": ["-m", "my_secops_server"],
      "env": {
        "SPINDL_INSTANCE_PREFIX": "prod"
      }
    }
  }
}
```

stdio carries no credentials, so authentication does not apply to it. See
[Authentication](authentication.md#stdio) for what an `Authenticator` means
on stdio.

## HTTP Streamable

HTTP-based transport using the MCP SDK's streamable HTTP protocol.

```python
asyncio.run(server.run_http(host="0.0.0.0", port=8000))
```

**Requires:** `pip install cognisn-spindl[http]` (installs `uvicorn`)

**Use when:**
- Deploying as a networked service
- Running in containers (Docker, Kubernetes)
- Multi-client scenarios
- Per-request instance prefixing is needed

**Endpoint:** `POST /mcp`. The endpoint is stateless and answers with JSON.
Clients speaking protocol 2026-07-28 send one `POST` per request; `GET` and
`DELETE` are answered `405` for them.

### Instance Prefix Header

The HTTP transport reads the `X-Spindl-Prefix` header from each request:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Spindl-Prefix: prod" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

Each request can have a different prefix. Concurrent requests are isolated via `contextvars`.

<!-- docs-test
async with docs_client(server) as client:
    names = {tool["name"] for tool in await client.list({"X-Spindl-Prefix": "prod"})}
assert "prod_secops_ping" in names
-->

### Docker Deployment

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install "cognisn-spindl[http]"
ENV SPINDL_INSTANCE_PREFIX=prod
EXPOSE 8000
CMD ["python", "-m", "my_server"]
```

<!-- docs-test
docs_module("my_server.app", create_server=lambda: server)
-->

```python
# my_server/__main__.py
import asyncio
from my_server.app import create_server

server = create_server()
asyncio.run(server.run_http(host="0.0.0.0", port=8000))
```

## SSE (Server-Sent Events)

SSE transport for streaming connections.

```python
asyncio.run(server.run_sse(host="0.0.0.0", port=8000))
```

**Requires:** `pip install cognisn-spindl[http]` (installs `uvicorn`)

**Use when:**
- Clients that support SSE but not HTTP streamable
- Streaming updates are needed

The MCP specification lists the HTTP+SSE transport as deprecated in favour
of HTTP streamable; prefer HTTP streamable for new deployments.

**Endpoints:**
- `GET /sse` -- SSE connection endpoint
- `POST /messages/` -- Message posting endpoint

### Instance Prefix Header

Send `X-Spindl-Prefix` on the `GET` that opens the stream **and on every
`POST` to the messages endpoint**. The `mcp` SDK handles each request in the
context of the `POST` that carried it, so spindl reads the prefix from that
`POST`; a prefix sent only on the `GET` does not apply to tool calls.

## Authentication (HTTP, SSE and WSGI)

The HTTP streamable, SSE and WSGI transports can require every caller to
authenticate. Spindl is a **resource server** only: it checks credentials
that something else issued, through an `Authenticator` you supply, and never
issues them. [Authentication and Tool Access](authentication.md) describes
it in full; this is the shape:

```python
from spindl import AuthConfig
from spindl.auth import ApiKeyAuthenticator, InMemoryApiKeyStore, ScopeAuthoriser

authenticator = ApiKeyAuthenticator(InMemoryApiKeyStore(), authoriser=ScopeAuthoriser())
secured = MCPServer(
    prefix="secops",
    auth=AuthConfig(
        authenticator=authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
        credential_headers=authenticator.credential_headers,
    ),
)
secured.register(MyTool())
asyncio.run(secured.run_http(port=8000))
```

With `auth` set:

- Requests without a valid credential receive `401` with a `WWW-Authenticate:
  Bearer` challenge whose `resource_metadata` points at the metadata document.
- Requests whose identity lacks one of `required_scopes` receive `403`.
- Tools the caller may not use are hidden, or, with `denial_mode="step_up"`,
  answered `403` `insufficient_scope` naming the missing permissions.
- With an `Authenticator`, tools require reach unless they set
  `requires_reach = False`; see
  [Tool access is not reach](authentication.md#tool-access-is-not-reach).
- The RFC 9728 protected-resource metadata document is served at
  `/.well-known/oauth-protected-resource` followed by the resource path (for
  the example above, `/.well-known/oauth-protected-resource/mcp`). Its
  `resource` and `authorization_servers` values are exactly the strings
  configured, with no trailing slash added, so they can be compared as strings
  with the authorisation server's own metadata. Its `scopes_supported` adds
  every permission a registered tool declares.

<!-- docs-test
async with docs_client(secured) as client:
    anonymous = await client.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
assert anonymous.status_code == 401
assert metadata.json()["resource"] == "https://mcp.example.com/mcp"
assert metadata.json()["authorization_servers"] == ["https://auth.example.com/"]
-->

### Reading the caller's identity in a tool

Tools read the call's identity and reach from `self.context`, so the
`execute(**params)` contract is unchanged:

```python
class SearchTool(BaseTool):
    name = "search"
    description = "Search the caller's records"
    category = "data"
    read_only = True
    destructive = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        context = self.context
        identity = context.identity if context else None  # None when auth is off
        reach = context.reach if context else None  # apply it to every query
        return {"success": True, "data": {"subject": identity.subject if identity else None}}
```

`self.context` is a `ToolContext` (`identity`, `reach`, `instance_prefix`),
and `spindl.current_identity()` returns the same `Identity` (`subject`,
`client_id`, `tool_permissions`, `reach`, `expires_at`) from anywhere in the
request, or `None` when authentication is off.

### Building the ASGI app yourself

`server.build_http_app()` and `server.build_sse_app()` return the Starlette
application that `run_http()` and `run_sse()` serve. The HTTP application has
a lifespan that must be running.

### Mounting behind an existing gateway

If another Starlette or FastAPI application already owns the origin (TLS, the
authorisation server, discovery documents), Spindl can live inside it. There
are two ways, and the first is preferred when the external URL must be exact.

**Register the endpoint on your own router.** `http_endpoint()` returns the
transport as a raw ASGI callable that carries its own authentication stack when
`auth` is set, and `http_lifespan` runs the session manager:

<!-- docs-test
server = MCPServer(prefix="secops")
server.register(MyTool())
-->

```python
from starlette.applications import Starlette
from starlette.routing import Route

endpoint = await server.http_endpoint()
gateway = Starlette(
    routes=[
        Route("/mcp", endpoint, methods=["POST", "GET", "DELETE"]),
        # ... the gateway's own routes
    ],
    lifespan=server.http_lifespan,   # or nest it inside your own lifespan
)
```

<!-- docs-test
import httpx

async with gateway.router.lifespan_context(gateway):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
assert resp.status_code == 200
assert "secops_ping" in {tool["name"] for tool in resp.json()["result"]["tools"]}
-->

The external URL is exactly `/mcp`, with no redirect.

**Mount the app under a prefix.** Serve at the sub-application root and mount:

```python
app = await server.build_http_app(path="/")
gateway.mount("/mcp", app)
```

Note that Starlette answers a mounted sub-application at `/mcp/` and sends a
`307` for a bare `/mcp`. The `mcp` SDK client follows redirects, so it works;
other clients may not. For SSE, `build_sse_app(sse_path=..., messages_path=...)`
accepts the same treatment, and the messages URL advertised to clients is
automatically prefixed with the mount path.

**Let the gateway serve discovery.** When the gateway already publishes the
RFC 9728 protected-resource document at the origin, stop Spindl registering
its own copy while keeping authentication and the `401`/`403` challenges:

```python
auth = AuthConfig(
    authenticator=authenticator,
    resource_server_url="https://mcp.example.com/mcp",
    authorization_servers=["https://auth.example.com/"],
    serve_metadata=False,
)
```

The `401` challenge's `resource_metadata` URL derives from
`resource_server_url`, so it keeps pointing at the document the gateway serves.

## WSGI (Flask, Django and other WSGI servers)

The HTTP streamable transport can also run inside a WSGI application. Install
the `wsgi` extra, which brings in `a2wsgi`:

```bash
pip install cognisn-spindl[wsgi]
```

Without it, `server.wsgi_app()` raises `ImportError` naming that command.
Importing `spindl` never needs `a2wsgi` or Flask.

### Flask

`spindl.wsgi.init_app()` mounts the server on a Flask application with
Werkzeug's `DispatcherMiddleware`. Requests under the path go to Spindl and
every other request reaches your Flask routes as before:

```python
from flask import Flask
from spindl import MCPServer
from spindl.wsgi import init_app

server = MCPServer(prefix="secops")
server.register(MyTool())

app = Flask(__name__)
init_app(app, server, path="/mcp")   # returns the bridge
```

<!-- docs-test
flask_client = app.test_client()
resp = flask_client.post(
    "/mcp",
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    headers={"Accept": "application/json, text/event-stream"},
)
assert resp.status_code == 200
assert "secops_ping" in {tool["name"] for tool in resp.get_json()["result"]["tools"]}
server.wsgi_app().close()
-->

`init_app()` refuses a second registration on the same application with
`RuntimeError`. It imports Werkzeug only when called.

### Any other WSGI application

`server.wsgi_app()` returns a PEP 3333 application. Mount it wherever your
framework mounts a WSGI application; it serves the MCP endpoint at its mount
point (an empty or `/` `PATH_INFO`) and answers `404` below it:

<!-- docs-test
server = MCPServer(prefix="secops")
server.register(MyTool())


def existing_wsgi_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"existing"]
-->

```python
from werkzeug.middleware.dispatcher import DispatcherMiddleware

bridge = server.wsgi_app()
application = DispatcherMiddleware(existing_wsgi_app, {"/mcp": bridge})
```

<!-- docs-test
from werkzeug.test import Client

wsgi_client = Client(application)
assert wsgi_client.get("/").get_data() == b"existing"
assert wsgi_client.get("/mcp").status_code == 405  # JSON only, no SSE over WSGI
assert server.wsgi_app() is bridge
bridge.close()
-->

Calling `wsgi_app()` again returns the same bridge, so a server never runs two
session managers.

### Authentication, prefixing and tool access

The bridge runs the same endpoint as `http_endpoint()`, so nothing changes:
with `auth` set, an unauthenticated request receives `401` and a request
lacking a required scope receives `403`, each with its `WWW-Authenticate`
challenge; `X-Spindl-Prefix` selects the instance prefix; the authenticator's
`authorise()` applies to `tools/list` and `tools/call`; reach is required as
on any other transport; and `denial_mode="step_up"` answers `403`.

When `AuthConfig.serve_metadata` is set, the bridge also answers the RFC 9728
document whenever the request's full path (`SCRIPT_NAME` plus `PATH_INFO`) is
the document's path, `/.well-known/oauth-protected-resource` followed by the
path of `resource_server_url`. `init_app()` routes that path to the bridge for
you. With any other host, route it to the same bridge yourself, for example
`DispatcherMiddleware(app, {"/mcp": bridge,
"/.well-known/oauth-protected-resource/mcp": bridge})`, or set
`serve_metadata=False` and publish the document elsewhere.

### The background thread and its lifecycle

The bridge owns one background thread, named `spindl-wsgi`, running an asyncio
event loop. On that loop it enters `http_lifespan()` once, for the life of the
bridge, and runs the endpoint for each request. A WSGI worker thread reads the
request body, hands the request to the loop and waits for the complete
response, so requests from many worker threads run concurrently on the loop.

- The thread starts on the first request, or earlier with `bridge.start()`,
  which returns once the lifespan is running.
- `bridge.close(timeout=10.0)` stops it: requests in flight get up to
  `timeout` seconds to finish, any still running are answered `503`, then the
  lifespan exits, the server cleans up (the spooler, if configured) and the
  thread is joined. `close()` is safe to call more than once.
- After `close()`, calling the bridge raises `RuntimeError`, and so does
  `server.wsgi_app()`, because a session manager runs only once. Build a new
  `MCPServer` to serve again.
- The thread is not a daemon thread, so it is never killed mid-request. An
  exit hook closes every open bridge when the interpreter exits, so a process
  that never calls `close()` still exits cleanly.
- With a pre-forking server such as gunicorn, each worker process gets its own
  bridge and thread. Create the bridge in the worker (the default, since the
  thread starts on the first request), not in the master before forking.

### Limits

- Responses are JSON. The bridge offers no Server-Sent Events: `GET` on the
  endpoint is answered `405` with `Allow: POST`. Use `build_sse_app()` under an
  ASGI server if you need the SSE transport.
- A response is returned to the WSGI server only when complete.
- A client that disconnects while its request runs is not detected until the
  response is written; the tool call runs to completion.

## Choosing a Transport

| Transport | Clients | Scaling | Auth | Instance Prefix |
|-----------|---------|---------|------|-----------------|
| stdio | Local only | Single client | N/A | Env var only |
| HTTP | Networked | Multi-client | `AuthConfig` | Header + env var |
| SSE | Networked | Multi-client | `AuthConfig` | Header (on the `GET` and every `POST`) + env var |
| WSGI | Networked, inside a WSGI app | As the WSGI server | `AuthConfig` | Header + env var |

### Recommendation

- **Development / local use:** stdio
- **Production deployment:** HTTP streamable
- **Inside an existing Flask or Django application:** WSGI
- **Legacy client compatibility:** SSE

## Multi-Transport Entrypoint

You can support multiple transports with a command-line argument:

```python
import asyncio
import sys
from spindl import MCPServer, SpoolerConfig

def main():
    server = MCPServer(
        prefix="secops",
        spooler=SpoolerConfig(),
    )
    # Register your tools
    server.register(MyTool())

    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    if transport == "stdio":
        asyncio.run(server.run_stdio())
    elif transport == "http":
        asyncio.run(server.run_http(port=8000))
    elif transport == "sse":
        asyncio.run(server.run_sse(port=8000))
    else:
        print(f"Unknown transport: {transport}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

<!-- docs-test
saved_argv = sys.argv
try:
    for choice in ("stdio", "http", "sse"):
        sys.argv = ["my_server.py", choice]
        main()
    sys.argv = ["my_server.py", "carrier-pigeon"]
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("an unknown transport should exit")
finally:
    sys.argv = saved_argv
-->

```bash
python my_server.py stdio   # Local
python my_server.py http    # Networked
python my_server.py sse     # SSE
```
