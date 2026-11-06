# Architecture

This document describes the internal architecture of spindl and how the components interact.

## Component Overview

```
MCPServer (server.py)
├── PrefixResolver (prefix.py)
│   ├── Server prefix (set in code)
│   ├── Instance prefix (env var / HTTP header)
│   ├── Known tool names registry
│   └── @placeholder resolution engine
├── ToolRegistry (registry.py)
│   ├── Tools stored by bare name
│   ├── MCP Tool definitions with annotations (prefixed at boundary)
│   ├── Access check per request (from the Authenticator)
│   └── Guide rendering (with placeholder resolution)
├── Authentication (auth/) [optional]
│   ├── AuthConfig, Authenticator, Credentials, Identity, ToolContext
│   ├── HTTP stack: credentials, 401/403 challenges, RFC 9728 metadata
│   ├── 0.4 adapters (token_verifier, tool_visibility)
│   └── Reference ApiKeyAuthenticator, ScopeAuthoriser, JwtAuthenticator
├── MCP SDK Server (mcp.server.Server)
│   ├── on_list_tools handler
│   └── on_call_tool handler
├── ResponseSpooler (spooler/) [optional]
│   ├── SpoolerConfig
│   ├── SQLite database (or an injected backend)
│   └── QueryEngine
├── Skills Guide Tools (skills/) [auto-registered]
│   ├── list_tools
│   └── describe_tool
├── Spooler Tools (spooler/tools/) [auto-registered when spooler enabled]
│   ├── spooler_list
│   ├── spooler_query
│   ├── spooler_aggregate
│   └── spooler_distinct
└── WsgiBridge (wsgi.py) [optional, the wsgi extra]
```

## Lifecycle

### 1. Construction

```python
from spindl import MCPServer, SpoolerConfig

server = MCPServer(prefix="secops", spooler=SpoolerConfig())
```

- `PrefixResolver("secops")` is created
- `ToolRegistry(prefix_resolver)` is created
- With `auth`, the authenticator (or the 0.4 adapter) is installed as the
  registry's access check
- Spooler config is stored (not yet initialised)

### 2. Tool Registration

<!-- docs-test
from typing import Any

from spindl import BaseTool


class MyTool(BaseTool):
    name = "list_devices"
    description = "List devices"
    category = "inventory"
    read_only = True
    destructive = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": []}
-->

```python
server.register(MyTool())
```

- Tool is stored in the registry by its **bare name**
- Registration checks the tool's declarations: a tool cannot be both
  `read_only` and `destructive`, and every name in `permissions` must be a
  valid OAuth scope token (`ValueError` otherwise)
- Bare name is registered with the `PrefixResolver` for `@placeholder` resolution

### 3. Setup (async, called once before transport starts)

```python
await server._setup()
```

This happens automatically when you call `run_stdio()`, `run_http()`, or `run_sse()`, or build an app or endpoint.

1. **Spooler initialisation** (if configured):
   - `ResponseSpooler` is created and `await initialise_async()` opens its backend
   - 4 spooler tools are auto-registered with the spooler reference
2. **Skills guide registration**:
   - `list_tools` and `describe_tool` are auto-registered with the registry reference
3. **Annotation warning**:
   - One warning names every tool declaring neither `read_only` nor
     `destructive` (see [Annotations](annotations.md))
4. **MCP SDK server creation**:
   - `mcp.server.Server(name, on_list_tools=..., on_call_tool=...)` is created

<!-- docs-test
assert {"list_devices", "list_tools", "describe_tool", "spooler_query"} <= set(
    server._prefix_resolver.known_names
)
await server._cleanup()
-->

### 4. Request Handling

On HTTP, SSE and WSGI with `auth` set, the authentication stack runs first:
it reads the credentials, calls `Authenticator.authenticate()`, answers
`401` or `403` when it must, and publishes the `Identity` for the request.
Then, when the MCP client calls a tool:

```
Client sends: tools/call "secops_list_devices" {"limit": 50}
                    │
                    ▼
        MCPServer._handle_call_tool()
                    │
        ┌───────────┴───────────┐
        │ Registry lookup by    │
        │ wire name (strip      │
        │ prefix → bare name)   │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ Tool access:          │
        │ authorise(identity,   │
        │ tool, "call")         │
        │ denied → unknown tool │
        │ (or 403 in step_up)   │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ Reach: required and   │
        │ missing → REACH_      │
        │ REQUIRED, tool not run│
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ self.context set for  │
        │ this call (identity,  │
        │ reach, prefix)        │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ tool.check_arguments()│
        │ reject undeclared     │
        │ arguments             │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ await tool.execute()  │
        │ (validates InputModel,│
        │ applies reach)        │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ _maybe_spool_response │
        │ (if tool opts in;     │
        │ spool scoped to the   │
        │ caller's subject)     │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ Resolve @placeholders │
        │ in JSON output        │
        └───────────┬───────────┘
                    │
                    ▼
        Return TextContent to client
```

`tools/list` applies the same access decision to every registered tool
(action `"list"`), so a caller is only shown the tools it may use.

### 5. Cleanup

```python
await server._cleanup()
```

- Spooler database is closed
- If `db_cleanup_on_exit=True`, the SQLite file is deleted

## Key Design Decisions

### Tool access and reach are separate controls

The authenticator's `authorise()` decides whether a caller may list and call
a tool. It runs in the registry, before any tool code, so every path
(`tools/list`, `tools/call`, `list_tools`, `describe_tool`) agrees. Reach,
what a permitted call may touch, is carried on the `Identity` but opaque to
spindl: only the tool knows what it reads and writes, so only the tool can
apply it. spindl's part is to fail closed: with an `Authenticator`, a tool
that requires reach is not run when the credential carries none. See
[Tool access is not reach](authentication.md#tool-access-is-not-reach).

### Undeclared arguments are rejected, not dropped

`_handle_call_tool` calls `tool.check_arguments()` before `execute()`, so a
tool is protected whether or not it validates its own parameters. The
boundary is where the input schema was advertised, so it is where a
mismatch belongs.

The reason is specific to a model-facing API. A model generalises across a
server's schema and will pass a sibling tool's parameter sooner or later.
Dropping it silently yields a correct-looking answer to a different
question, which the model reports as fact; an explicit `INVALID_ARGUMENTS`
error naming the accepted parameters is recovered from in one turn. Tools
that genuinely take free-form arguments set
`reject_unknown_arguments = False`.

### Undeclared annotations are not sent

`tools/list` carries only the hints a tool declares, so a host applies the
MCP defaults (possibly destructive) to anything left undeclared, rather than
spindl guessing on the tool's behalf. The start-up warning makes the gap
visible.

### Tools are stored by bare name

The registry maps `"list_devices"` → `Tool instance`. Prefixing only happens at two boundaries:

1. **`tool_definitions()`** -- when listing tools for the MCP client
2. **`lookup(wire_name)`** -- when dispatching a tool call

This means the prefix can change per-request (HTTP header) without re-registering tools.

### @placeholder resolution is lazy

Placeholders in guide text are resolved at render time, not at registration time. This ensures:

- The full prefix (including runtime instance prefix) is applied
- All tool names are registered before resolution happens
- The same guide text works regardless of deployment configuration

### Spooler guidance uses @placeholders

The `ResponseSpooler._build_summary()` method embeds tool references using `@spooler_query` syntax. The `MCPServer._run_tool()` method resolves all placeholders in the JSON output before returning to the client. This means spooler summaries automatically use the correct prefixed tool names.

### MCP SDK integration uses the low-level API

Spindl uses `mcp.server.Server` (not `FastMCP`) for full control over:

- Tool schema generation (from Pydantic InputModels)
- Tool dispatch routing (prefix-aware)
- Tool access and reach checks before dispatch
- Response post-processing (spooling, placeholder resolution)
- Transport selection

Spindl requires `mcp` 2.3 or later (below 3). It registers its `tools/list`
and `tools/call` handlers through the `Server` constructor's `on_list_tools`
and `on_call_tool` arguments, and speaks protocol revision 2026-07-28 on
every transport.

### The spooler core has zero external dependencies

`config.py`, `spooler.py`, and `query_engine.py` use only Python stdlib (`sqlite3`, `json`, `hashlib`, `copy`, `re`). The `pydantic` dependency is only in the tool layer (`InputModel` definitions) and response types.

## Module Dependency Graph

```
prefix.py           ← stdlib only (re, os, contextvars)
    ↑
auth/_types.py      ← stdlib only (Authenticator, Identity, Credentials, ToolContext)
auth/_context.py    ← auth/_types (context variables)
    ↑
tool.py             ← pydantic, auth/_types, auth/_context
    ↑
registry.py         ← prefix, tool, auth, mcp.types (lazy import)
    ↑
responses/          ← pydantic
    ↑
skills/             ← tool, responses, registry
    ↑
spooler/config.py   ← stdlib only
spooler/spooler.py  ← spooler/config (stdlib only)
spooler/query_engine.py ← spooler/config (stdlib only)
    ↑
spooler/tools/      ← tool, responses, spooler core
    ↑
auth/ (http, config, adapters, api_key, scopes, jwt)
                    ← auth/_types, starlette and mcp (http), pyjwt (jwt)
    ↑
server.py           ← all of above + mcp.server
    ↑
wsgi.py             ← server, a2wsgi (lazy import; the wsgi extra)
```
