# Transports

Spindl supports three MCP transport mechanisms. Your tools don't change -- only the `run_*()` method differs.

Spindl requires the `mcp` SDK 2.3 or later (below 3.0) and speaks MCP protocol revision 2026-07-28 on every transport, while still answering clients that use the earlier `initialize` handshake.

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

## HTTP Streamable

HTTP-based transport using the MCP SDK's streamable HTTP protocol.

```python
asyncio.run(server.run_http(host="0.0.0.0", port=8000))
```

**Requires:** `pip install spindl[http]` (installs `uvicorn`)

**Use when:**
- Deploying as a networked service
- Running in containers (Docker, Kubernetes)
- Multi-client scenarios
- Per-request instance prefixing is needed

**Endpoint:** `POST /mcp`

### Instance Prefix Header

The HTTP transport reads the `X-Spindl-Prefix` header from each request:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "X-Spindl-Prefix: prod" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

Each request can have a different prefix. Concurrent requests are isolated via `contextvars`.

### Docker Deployment

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install spindl[http]
ENV SPINDL_INSTANCE_PREFIX=prod
EXPOSE 8000
CMD ["python", "-m", "my_server"]
```

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

**Requires:** `pip install spindl[http]` (installs `uvicorn`)

**Use when:**
- Clients that support SSE but not HTTP streamable
- Streaming updates are needed

**Endpoints:**
- `GET /sse` -- SSE connection endpoint
- `POST /messages/` -- Message posting endpoint

### Instance Prefix Header

Same as HTTP transport -- reads `X-Spindl-Prefix` from the initial SSE connection request.

## Authentication (HTTP and SSE)

The HTTP and SSE transports can require a bearer token on every request.
Spindl acts as an OAuth 2.1 **resource server** only: it verifies tokens that
an external authorisation server has already issued, enforces scopes, and
exposes the caller's identity to tools. It does not implement login, consent,
client registration, or token issue; those stay with your authorisation server.
stdio is unaffected.

```python
from mcp.server.auth.provider import AccessToken
from spindl import AuthConfig, MCPServer


class MyVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        # Introspect or validate the token against your authorisation server.
        # Return None for an invalid or expired token.
        ...


server = MCPServer(
    prefix="secops",
    auth=AuthConfig(
        token_verifier=MyVerifier(),
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
        required_scopes=["read"],
    ),
)
asyncio.run(server.run_http(port=8000))
```

With `auth` set:

- Requests without a valid token receive `401` with a `WWW-Authenticate:
  Bearer` challenge whose `resource_metadata` points at the metadata document.
- Requests whose token lacks a required scope receive `403`.
- The RFC 9728 protected-resource metadata document is served at
  `/.well-known/oauth-protected-resource` followed by the resource path (for
  the example above, `/.well-known/oauth-protected-resource/mcp`). Its
  `resource` and `authorization_servers` values are exactly the strings
  configured, with no trailing slash added, so they can be compared as strings
  with the authorisation server's own metadata.

To show different callers different tools, see [Tool Visibility](visibility.md).

### Reading the caller's identity in a tool

Tools read the authenticated caller through a per-request context accessor,
so the `execute(**params)` contract is unchanged:

```python
from spindl import BaseTool, current_identity


class SearchTool(BaseTool):
    name = "search"
    ...

    async def execute(self, **params) -> dict:
        identity = current_identity()  # AccessToken, or None when auth is off
        if identity is not None and "search:privileged" not in identity.scopes:
            return {"error": "insufficient scope"}
        ...
```

`current_identity()` returns the SDK's `AccessToken` (`subject`, `client_id`,
`scopes`, `expires_at`, `claims`) during an authenticated request and `None`
otherwise.

### Building the ASGI app yourself

`server.build_http_app()` and `server.build_sse_app()` return the Starlette
application that `run_http()` and `run_sse()` serve. The HTTP application has
a lifespan that must be running.

### Mounting behind an existing gateway

If another Starlette or FastAPI application already owns the origin (TLS, the
authorisation server, discovery documents), Spindl can live inside it. There
are two ways, and the first is preferred when the external URL must be exact.

**Register the endpoint on your own router.** `http_endpoint()` returns the
transport as a raw ASGI callable that carries its own bearer-token stack when
`auth` is set, and `http_lifespan` runs the session manager:

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
its own copy while keeping token verification and the `401`/`403` challenges:

```python
auth = AuthConfig(..., serve_metadata=False)
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

`init_app()` refuses a second registration on the same application with
`RuntimeError`. It imports Werkzeug only when called.

### Any other WSGI application

`server.wsgi_app()` returns a PEP 3333 application. Mount it wherever your
framework mounts a WSGI application; it serves the MCP endpoint at its mount
point (an empty or `/` `PATH_INFO`) and answers `404` below it:

```python
from werkzeug.middleware.dispatcher import DispatcherMiddleware

bridge = server.wsgi_app()
application = DispatcherMiddleware(existing_wsgi_app, {"/mcp": bridge})
```

Calling `wsgi_app()` again returns the same bridge, so a server never runs two
session managers.

### Authentication, prefixing and visibility

The bridge runs the same endpoint as `http_endpoint()`, so nothing changes:
with `auth` set, an unauthenticated request receives `401` and a request
lacking a scope receives `403`, each with its `WWW-Authenticate` challenge;
`X-Spindl-Prefix` selects the instance prefix; the visibility hook applies to
`tools/list` and `tools/call`.

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
| HTTP | Networked | Multi-client | Custom middleware | Header + env var |
| SSE | Networked | Multi-client | Custom middleware | Header + env var |

### Recommendation

- **Development / local use:** stdio
- **Production deployment:** HTTP streamable
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
    server.register(...)

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

```bash
python my_server.py stdio   # Local
python my_server.py http    # Networked
python my_server.py sse     # SSE
```
