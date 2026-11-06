# Spindl

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=bugs)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=ncloc)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_spindl&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=Cognisn_spindl)

A Python framework for building [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers with hierarchical tool name prefixing, on-demand skills guides, built-in response spooling for large data sets, tool annotations, and authentication with per-caller tool access.

## The Problem

When an MCP client connects to multiple servers, tool name collisions cause confusion. If two servers both expose `list_devices`, the LLM doesn't know which one to call. Worse, tool descriptions and guides that reference other tools by name become ambiguous. And once a server is shared, every caller needs to see only the tools, and the data, that are theirs.

## Features

- **Hierarchical prefix namespacing.** Every tool name is prefixed with a server identity (`secops_list_devices`), with an optional runtime instance prefix for multi-deployment scenarios (`prod_secops_list_devices`).
- **Skills guide tools.** Instead of bloating tool descriptions with lengthy usage guides, spindl auto-registers `list_tools` and `describe_tool` tools that the LLM calls on demand.
- **Response spooling.** Large array responses are stored in an ephemeral SQLite database (or your own backend), with query, aggregate and distinct tools for exploring them.
- **Tool annotations.** Declare `title`, `read_only`, `destructive`, `idempotent` and `open_world` on a tool, and hosts such as Claude Desktop group it correctly. spindl warns at start-up about tools that declare neither `read_only` nor `destructive`.
- **Authentication and tool access.** Plug in an `Authenticator` and spindl reads the credentials, answers the `401` and `403` challenges, publishes the RFC 9728 metadata and hides (or step-up challenges) tools a caller may not use. Reference API key, scope and JWT implementations are included. spindl is a resource server only.
- **Reach, failing closed.** Each identity carries its reach (what its calls may touch), handed to the tool as `self.context.reach`. With an `Authenticator`, a tool that requires reach never runs for a credential that carries none.
- **Every transport.** stdio, HTTP streamable and SSE, mountable in Starlette and FastAPI, or inside Flask, Django and other WSGI applications. MCP protocol revision 2026-07-28.

## Installation

```bash
pip install cognisn-spindl                # core: stdio, and ASGI apps you serve yourself
pip install "cognisn-spindl[http]"        # plus uvicorn, for run_http() and run_sse()
pip install "cognisn-spindl[wsgi]"        # plus a2wsgi, for Flask, Django and other WSGI hosts
pip install "cognisn-spindl[http,wsgi]"   # both
```

For development: `pip install -e ".[dev,http,wsgi]"` from a clone.

## Quick Start

```python
import asyncio
from pydantic import BaseModel, Field
from spindl import MCPServer, BaseTool, SpoolerConfig

class ListDevices(BaseTool):
    name = "list_devices"
    description = "List all monitored devices"
    category = "inventory"
    title = "List devices"
    read_only = True          # annotations: hosts group tools by these
    destructive = False
    spooler_auto_detect = True  # Auto-spool large responses

    class InputModel(BaseModel):
        limit: int = Field(default=50, ge=1, le=500, description="Max devices to return")

    def guide(self) -> str:
        return (
            "# @list_devices\n\n"
            "Returns all monitored devices. Large result sets are "
            "automatically spooled -- use @spooler_query to filter "
            "and paginate through the data.\n\n"
            "## Examples\n\n"
            '```json\n{"limit": 100}\n```\n'
        )

    async def execute(self, **params) -> dict:
        validated = self.validate_input(params)
        # Your API logic here
        devices = [{"id": i, "name": f"device-{i}"} for i in range(validated.limit)]
        return {"success": True, "data": devices}

server = MCPServer(
    prefix="secops",
    spooler=SpoolerConfig(),  # Enables response spooling
)
server.register(ListDevices())

# Run on stdio (for Claude Desktop, Cursor, etc.)
asyncio.run(server.run_stdio())
```

<!-- docs-test
async with docs_client(server) as client:
    listed = {tool["name"]: tool for tool in await client.list()}
assert set(listed) == {
    "secops_list_devices",
    "secops_list_tools",
    "secops_describe_tool",
    "secops_spooler_list",
    "secops_spooler_query",
    "secops_spooler_aggregate",
    "secops_spooler_distinct",
}
assert listed["secops_list_devices"]["annotations"] == {
    "title": "List devices",
    "readOnlyHint": True,
    "destructiveHint": False,
}
await server._cleanup()
-->

This server exposes the following tools to the MCP client:

| Wire Name | Source |
|-----------|--------|
| `secops_list_devices` | Your custom tool |
| `secops_list_tools` | Auto-registered skills guide |
| `secops_describe_tool` | Auto-registered skills guide |
| `secops_spooler_list` | Auto-registered (spooler enabled) |
| `secops_spooler_query` | Auto-registered (spooler enabled) |
| `secops_spooler_aggregate` | Auto-registered (spooler enabled) |
| `secops_spooler_distinct` | Auto-registered (spooler enabled) |

## Authentication in Brief

Serve the same tools over HTTP to callers holding API keys. Each key grants
tool permissions (which tools) and reach (what those tools may touch), and
the tool applies the reach to its own query:

```python
from typing import Any

from spindl import AuthConfig
from spindl.auth import (
    ApiKeyAuthenticator,
    ApiKeyRecord,
    InMemoryApiKeyStore,
    ScopeAuthoriser,
    generate_api_key,
    hash_api_key,
)

DEVICES = [
    {"id": "dev-1", "site": "site-a"},
    {"id": "dev-2", "site": "site-b"},
]

class ListSiteDevices(BaseTool):
    name = "list_site_devices"
    description = "List the devices at the caller's sites"
    category = "inventory"
    title = "List site devices"
    read_only = True
    destructive = False
    permissions = ["devices:read"]    # tool access: who may call it

    async def execute(self, **params: Any) -> dict:
        self.validate_input(params)
        sites = self.context.reach if self.context else None   # reach: what it may touch
        if not isinstance(sites, frozenset):
            return {"success": False, "error": "no site reach"}
        return {"success": True, "data": [d for d in DEVICES if d["site"] in sites]}

store = InMemoryApiKeyStore()
analyst_key = generate_api_key("secops")   # give this to the analyst once; store only the hash
store.add(
    ApiKeyRecord(
        key_id="analyst-1",
        key_hash=hash_api_key(analyst_key),
        subject="analyst@example.com",
        tool_permissions={"devices:read"},
        reach=frozenset({"site-a"}),
    )
)

authenticator = ApiKeyAuthenticator(store, authoriser=ScopeAuthoriser())
secured = MCPServer(
    prefix="secops",
    auth=AuthConfig(
        authenticator=authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
        credential_headers=authenticator.credential_headers,  # X-API-Key
    ),
)
secured.register(ListSiteDevices())
asyncio.run(secured.run_http(host="127.0.0.1", port=8000))
```

<!-- docs-test
async with docs_client(secured) as client:
    _, found = await client.call("secops_list_site_devices", {}, {"X-API-Key": analyst_key})
    anonymous = await client.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
assert found["data"] == [{"id": "dev-1", "site": "site-a"}]
assert anonymous.status_code == 401
# A session manager runs once; the WSGI example below serves this server again.
secured._session_manager = None
-->

A call without a valid key gets `401`; a key without `devices:read` never
sees the tool. Passing that check never limits what a tool touches, which is
why the tool filters by `self.context.reach` itself: read
[Tool access is not reach](docs/authentication.md#tool-access-is-not-reach)
before writing tools for a shared server.

## Prefix System

The server prefix is set in code (`MCPServer(prefix="secops")`). An instance
prefix can be added per deployment with `SPINDL_INSTANCE_PREFIX=prod`, or per
request with the `X-Spindl-Prefix: prod` header on the HTTP, SSE and WSGI
transports (on SSE, send it on the messages `POST`s too). Guides reference
other tools as `@bare_name`, resolved to the full wire name at render time:

```python
def guide(self) -> str:
    return "Use @list_devices to get devices. Query results with @spooler_query."
```

<!-- docs-test
from spindl import PrefixResolver

resolver = PrefixResolver("secops")
for known in ("list_devices", "spooler_query"):
    resolver.register_known_name(known)
assert resolver.resolve_placeholders(guide(None)) == (
    "Use secops_list_devices to get devices. Query results with secops_spooler_query."
)
-->

See [Prefix System](docs/prefix-system.md).

## Transports

```python
asyncio.run(server.run_stdio())                         # local clients
asyncio.run(server.run_http(host="0.0.0.0", port=8000))  # HTTP streamable at /mcp
asyncio.run(server.run_sse(host="0.0.0.0", port=8000))   # SSE at /sse and /messages/
```

`build_http_app()`, `http_endpoint()` and `build_sse_app()` give you the
ASGI application to mount in Starlette or FastAPI, and `wsgi_app()` and
`spindl.wsgi.init_app()` serve HTTP streamable from a WSGI application:

```python
from flask import Flask
from spindl.wsgi import init_app

app = Flask(__name__)
init_app(app, secured, path="/mcp")
```

<!-- docs-test
resp = app.test_client().post(
    "/mcp",
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    headers={"Accept": "application/json, text/event-stream", "X-API-Key": analyst_key},
)
assert resp.status_code == 200
secured.wsgi_app().close()
-->

See [Transports](docs/transports.md).

## Response Types

Spindl includes self-contained response types for consistent tool output:

```python
from spindl import ResponseEnvelope, ResponseMetadata, StructuredError, ErrorDetail

results = [{"id": 1}, {"id": 2}]

# Success response
success = ResponseEnvelope(
    success=True,
    data={"items": results},
    metadata=ResponseMetadata(
        total_results=len(results),
        returned_results=len(results),
    ),
).to_dict()

# Error response
failure = StructuredError(
    error=ErrorDetail(
        error_code="AUTH_ERROR",
        error_message="Invalid API key",
        retry_eligible=False,
        suggestion="Check your API key configuration.",
    ),
).to_dict()
```

<!-- docs-test
assert success["success"] is True and success["metadata"]["returned_results"] == 2
assert failure["success"] is False and failure["error"]["error_code"] == "AUTH_ERROR"
-->

## Documentation

| Page | Covers |
|------|--------|
| [Building Tools](docs/building-tools.md) | Tool classes, inputs, argument validation, guides, return values, spooling |
| [Annotations](docs/annotations.md) | `title`, `read_only`, `destructive`, `idempotent`, `open_world`, the start-up warning, category in `_meta` |
| [Authentication and Tool Access](docs/authentication.md) | `Authenticator`, `Identity`, `401` and `403`, denial modes, permissions, reach, the reference API key, scope and JWT implementations |
| [Transports](docs/transports.md) | stdio, HTTP streamable, SSE, mounting in ASGI gateways, WSGI and Flask |
| [Prefix System](docs/prefix-system.md) | Server and instance prefixes, `@placeholder` resolution |
| [Skills Guide](docs/skills-guide.md) | `list_tools` and `describe_tool` |
| [Response Spooler](docs/spooler.md) | Spooling large arrays, the query tools, backends, scope and expiry |
| [Architecture](docs/architecture.md) | How the components fit together |
| [Upgrading from 0.4](docs/upgrading-0.5.md) | Moving a 0.4 server to 0.5 |
| [Sample server](sample/README.md) | A runnable server using annotations, API keys, reach and Flask |

## Requirements

- Python >= 3.10
- `mcp >= 2.3, < 3` (MCP protocol revision 2026-07-28)
- `pydantic >= 2.0.0`
- `starlette` and `pyjwt[crypto]` (at the floors `mcp` 2.3 requires)
- `uvicorn >= 0.30.0` (optional, the `http` extra, for `run_http()` and `run_sse()`)
- `a2wsgi >= 1.10.0` (optional, the `wsgi` extra, for WSGI hosts)

## Licence

MIT
