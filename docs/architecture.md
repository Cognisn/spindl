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
│   ├── MCP Tool definitions (prefixed at boundary)
│   └── Guide rendering (with placeholder resolution)
├── MCP SDK Server (mcp.server.Server)
│   ├── list_tools handler
│   └── call_tool handler
├── ResponseSpooler (spooler/) [optional]
│   ├── SpoolerConfig
│   ├── SQLite database
│   └── QueryEngine
├── Skills Guide Tools (skills/) [auto-registered]
│   ├── list_tools
│   └── describe_tool
└── Spooler Tools (spooler/tools/) [auto-registered when spooler enabled]
    ├── spooler_list
    ├── spooler_query
    ├── spooler_aggregate
    └── spooler_distinct
```

## Lifecycle

### 1. Construction

```python
server = MCPServer(prefix="secops", spooler=SpoolerConfig())
```

- `PrefixResolver("secops")` is created
- `ToolRegistry(prefix_resolver)` is created
- Spooler config is stored (not yet initialised)

### 2. Tool Registration

```python
server.register(MyTool())
```

- Tool is stored in the registry by its **bare name**
- Bare name is registered with the `PrefixResolver` for `@placeholder` resolution

### 3. Setup (async, called once before transport starts)

```python
await server._setup()
```

This happens automatically when you call `run_stdio()`, `run_http()`, or `run_sse()`.

1. **Spooler initialisation** (if configured):
   - `ResponseSpooler` is created and `await initialise()` creates the SQLite database
   - 4 spooler tools are auto-registered with the spooler reference
2. **Skills guide registration**:
   - `list_tools` and `describe_tool` are auto-registered with the registry reference
3. **MCP SDK server creation**:
   - `mcp.server.Server` is created
   - `list_tools` and `call_tool` protocol handlers are registered

### 4. Request Handling

When the MCP client calls a tool:

```
Client sends: call_tool("secops_list_devices", {"limit": 50})
                    │
                    ▼
        MCPServer._handle_call_tool()
                    │
        ┌───────────┴───────────┐
        │ Strip prefix          │
        │ "secops_list_devices" │
        │   → "list_devices"    │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ Registry lookup       │
        │ tools["list_devices"] │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ Validate input via    │
        │ tool.InputModel       │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ await tool.execute()  │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │ _maybe_spool_response │
        │ (if tool opts in)     │
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

### 5. Cleanup

```python
await server._cleanup()
```

- Spooler database is closed
- If `db_cleanup_on_exit=True`, the SQLite file is deleted

## Key Design Decisions

### Tools are stored by bare name

The registry maps `"list_devices"` → `Tool instance`. Prefixing only happens at two boundaries:

1. **`get_mcp_tool_definitions()`** -- when listing tools for the MCP client
2. **`get_tool(wire_name)`** -- when dispatching a tool call

This means the prefix can change per-request (HTTP header) without re-registering tools.

### @placeholder resolution is lazy

Placeholders in guide text are resolved at render time, not at registration time. This ensures:

- The full prefix (including runtime instance prefix) is applied
- All tool names are registered before resolution happens
- The same guide text works regardless of deployment configuration

### Spooler guidance uses @placeholders

The `ResponseSpooler._build_summary()` method embeds tool references using `@spooler_query` syntax. The `MCPServer._handle_call_tool()` method resolves all placeholders in the JSON output before returning to the client. This means spooler summaries automatically use the correct prefixed tool names.

### MCP SDK integration uses the low-level API

Spindl uses `mcp.server.Server` (not `FastMCP`) for full control over:

- Tool schema generation (from Pydantic InputModels)
- Tool dispatch routing (prefix-aware)
- Response post-processing (spooling, placeholder resolution)
- Transport selection

### The spooler core has zero external dependencies

`config.py`, `spooler.py`, and `query_engine.py` use only Python stdlib (`sqlite3`, `json`, `hashlib`, `copy`, `re`). The `pydantic` dependency is only in the tool layer (`InputModel` definitions) and response types.

## Module Dependency Graph

```
prefix.py           ← stdlib only (re, os, contextvars)
    ↑
tool.py             ← pydantic
    ↑
registry.py         ← prefix, tool, mcp.types (lazy import)
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
server.py           ← all of above + mcp.server
```
