# Spindl

A Python framework for building [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers with hierarchical tool name prefixing, on-demand skills guides, and built-in response spooling for large data sets.

## The Problem

When an MCP client connects to multiple servers, tool name collisions cause confusion. If two servers both expose `list_devices`, the LLM doesn't know which one to call. Worse, tool descriptions and guides that reference other tools by name become ambiguous.

## The Solution

Spindl solves this with three capabilities:

- **Hierarchical prefix namespacing** -- Every tool name is automatically prefixed with a server identity (e.g. `secops_list_devices`), with an optional runtime instance prefix for multi-deployment scenarios (e.g. `prod_secops_list_devices`).
- **Skills guide tools** -- Instead of bloating tool descriptions with lengthy usage guides, spindl auto-registers `list_tools` and `describe_tool` tools that the LLM can call on demand.
- **Response spooling** -- Large array responses are automatically stored in an ephemeral SQLite database with query, aggregate, and distinct tools for efficient data exploration.

## Installation

```bash
pip install spindl
```

For HTTP/SSE transport support:

```bash
pip install spindl[http]
```

For development:

```bash
pip install spindl[dev]
```

## Quick Start

```python
import asyncio
from pydantic import BaseModel, Field
from spindl import MCPServer, BaseTool

class ListDevices(BaseTool):
    name = "list_devices"
    description = "List all monitored devices"
    category = "inventory"
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
        validated = self.InputModel(**params)
        # Your API logic here
        devices = [{"id": i, "name": f"device-{i}"} for i in range(validated.limit)]
        return {"success": True, "data": devices}

# Create server with prefix and optional spooler
from spindl import SpoolerConfig

server = MCPServer(
    prefix="secops",
    spooler=SpoolerConfig(),  # Enables response spooling
)
server.register(ListDevices())

# Run on stdio (for Claude Desktop, Cursor, etc.)
asyncio.run(server.run_stdio())
```

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

## Architecture

```
                         MCPServer
                        /    |     \
              PrefixResolver |  ToolRegistry
                             |       |
                    MCP SDK Server   Tools (bare names)
                    /    |    \        |
                stdio  http   sse   Prefixed at boundary
```

### Core Components

| Component | Module | Role |
|-----------|--------|------|
| `MCPServer` | `spindl.server` | Top-level orchestrator. Owns everything. |
| `PrefixResolver` | `spindl.prefix` | Hierarchical prefix engine with `@placeholder` resolution |
| `ToolRegistry` | `spindl.registry` | Stores tools by bare name, prefixes at the MCP boundary |
| `BaseTool` | `spindl.tool` | Clean base class for tool authors |
| `ResponseSpooler` | `spindl.spooler` | SQLite-backed large response handler |

### Design Principles

- **Tools never know their prefix.** They are stored by bare name internally. Prefixing happens at the MCP protocol boundary.
- **Guides use `@placeholder` syntax.** Write `@spooler_query` in your guide text; it resolves to `secops_spooler_query` (or `prod_secops_spooler_query`) at runtime.
- **The spooler core is stdlib-only.** No external dependencies beyond Python's built-in `sqlite3`, `json`, and `hashlib`.
- **Transports are swappable.** Call `run_stdio()`, `run_http()`, or `run_sse()` -- your tools don't change.

## Prefix System

### Level 1: Server Prefix (Code)

Set by the developer. Mandatory. Identifies the server.

```python
server = MCPServer(prefix="secops")
# All tools: secops_list_devices, secops_list_tools, ...
```

### Level 2: Instance Prefix (Runtime)

Optional. Identifies a deployment instance. Useful when the same server is deployed multiple times with different purposes.

**Via environment variable:**

```bash
export SPINDL_INSTANCE_PREFIX=prod
# All tools: prod_secops_list_devices, prod_secops_list_tools, ...
```

**Via HTTP header** (for HTTP/SSE transports):

```
X-Spindl-Prefix: prod
```

Header takes precedence over the environment variable. Each HTTP request can have a different prefix (isolated via `contextvars`).

### Placeholder Resolution

Tool guides reference other tools using `@bare_name` syntax:

```python
def guide(self) -> str:
    return "Use @list_devices to get devices. Query results with @spooler_query."
```

At runtime, these resolve to fully prefixed wire names:

```
"Use secops_list_devices to get devices. Query results with secops_spooler_query."
```

Only registered tool names are replaced. Unknown `@references` pass through untouched.

## Building Tools

### Minimal Tool

```python
from spindl import BaseTool

class Ping(BaseTool):
    name = "ping"
    description = "Health check"
    category = "meta"

    async def execute(self, **params) -> dict:
        return {"success": True, "data": "pong"}
```

### Tool with Parameters

```python
from pydantic import BaseModel, Field
from spindl import BaseTool

class SearchVulns(BaseTool):
    name = "search_vulns"
    description = "Search vulnerability database"
    category = "security"
    spooler_array_paths = ["results"]  # Spool the 'results' array

    class InputModel(BaseModel):
        query: str = Field(description="Search query")
        severity: str | None = Field(default=None, description="Filter by severity")
        limit: int = Field(default=50, ge=1, le=500, description="Max results")

    def guide(self) -> str:
        return (
            "# @search_vulns\n\n"
            "Search for vulnerabilities by keyword. Results are "
            "automatically spooled when large.\n\n"
            "## Parameters\n\n"
            "- **query** (required): Search keywords\n"
            "- **severity** (optional): Filter by critical/high/medium/low\n"
            "- **limit** (optional): Max results (default 50)\n\n"
            "## Examples\n\n"
            '```json\n{"query": "CVE-2024", "severity": "critical"}\n```\n\n'
            "## Follow-up\n\n"
            "Use @spooler_query to filter results, @spooler_aggregate "
            "for severity breakdowns, or @spooler_distinct to see "
            "affected vendors.\n"
        )

    async def execute(self, **params) -> dict:
        validated = self.InputModel(**params)
        # Your search logic here
        results = [...]
        return {"success": True, "data": {"results": results}}
```

### Tool Attributes Reference

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `""` | Bare tool name (required) |
| `description` | `str` | `""` | Short one-line description (required) |
| `category` | `str` | `""` | Grouping key for skills guide (required) |
| `spooler_array_paths` | `list[str] \| None` | `None` | Dot-notation paths to arrays to spool |
| `spooler_auto_detect` | `bool` | `False` | Auto-detect large arrays in response |
| `InputModel` | `type[BaseModel] \| None` | `None` | Pydantic model for input validation |

### Spooler Opt-In

Tools opt into response spooling via two attributes:

- **`spooler_array_paths`** -- Explicit dot-notation paths: `["results", "data.items"]`
- **`spooler_auto_detect`** -- Let the spooler find arrays automatically

When the response array exceeds the configured thresholds (`max_inline_items` or `max_inline_tokens`), it's stored in SQLite and replaced with a summary containing the `spool_id`.

## Response Spooler

### Configuration

```python
from spindl import MCPServer, SpoolerConfig

server = MCPServer(
    prefix="secops",
    spooler=SpoolerConfig(
        db_path="/tmp/spooler.db",      # SQLite file location
        max_inline_tokens=2000,          # Token threshold for spooling
        max_inline_items=10,             # Item count threshold
        default_page_size=20,            # Default records per query page
        max_page_size=50,                # Hard ceiling on page size
        summary_sample_size=3,           # Sample records in summary
        db_cleanup_on_exit=True,         # Delete DB on shutdown
    ),
)
```

All settings can also be configured via environment variables:

| Env Var | Default |
|---------|---------|
| `SPOOLER_DB_PATH` | `/tmp/mcp_spooler.db` |
| `SPOOLER_MAX_INLINE_TOKENS` | `2000` |
| `SPOOLER_MAX_INLINE_ITEMS` | `10` |
| `SPOOLER_DEFAULT_PAGE_SIZE` | `20` |
| `SPOOLER_MAX_PAGE_SIZE` | `50` |
| `SPOOLER_SUMMARY_SAMPLE_SIZE` | `3` |
| `SPOOLER_CLEANUP_ON_EXIT` | `true` |

### How It Works

1. A tool returns a response with a large array
2. The spooler detects the array exceeds thresholds
3. The array is stored in SQLite with a unique `spool_id`
4. The LLM receives a summary with record count, column names, statistics, sample records, and the `spool_id`
5. The LLM uses the spooler query tools to explore the data

### Spooler Query Tools

| Tool | Purpose |
|------|---------|
| `{prefix}_spooler_list` | List all available spooled data sets |
| `{prefix}_spooler_query` | Filter, sort, paginate, search records |
| `{prefix}_spooler_aggregate` | Group-by with count/sum/avg/min/max |
| `{prefix}_spooler_distinct` | Unique values and frequency counts |

## Skills Guide

Every spindl server auto-registers two tools:

### `{prefix}_list_tools`

Returns all registered tools grouped by category. No parameters needed.

```json
{
  "success": true,
  "data": {
    "total_tools": 7,
    "categories": {
      "inventory": [
        {"name": "secops_list_devices", "description": "List all monitored devices"}
      ],
      "skills": [
        {"name": "secops_list_tools", "description": "List all available tools..."},
        {"name": "secops_describe_tool", "description": "Get detailed usage guide..."}
      ],
      "spooler": [
        {"name": "secops_spooler_list", "description": "List all spooled data sets..."},
        ...
      ]
    }
  }
}
```

### `{prefix}_describe_tool`

Returns the detailed guide for a specific tool, with all `@placeholders` resolved to prefixed wire names.

```json
{"tool_name": "secops_list_devices"}
```

## Transports

### stdio

For local MCP clients (Claude Desktop, Cursor, VS Code, etc.):

```python
asyncio.run(server.run_stdio())
```

### HTTP Streamable

For networked deployments. Requires `pip install spindl[http]`.

```python
asyncio.run(server.run_http(host="0.0.0.0", port=8000))
```

The server reads the `X-Spindl-Prefix` header from each request for per-request instance prefixing.

### SSE (Server-Sent Events)

For streaming connections. Requires `pip install spindl[http]`.

```python
asyncio.run(server.run_sse(host="0.0.0.0", port=8000))
```

## Response Types

Spindl includes self-contained response types for consistent tool output:

```python
from spindl import ResponseEnvelope, ResponseMetadata, StructuredError, ErrorDetail

# Success response
return ResponseEnvelope(
    success=True,
    data={"items": results},
    metadata=ResponseMetadata(
        total_results=len(results),
        returned_results=len(results),
    ),
).to_dict()

# Error response
return StructuredError(
    error=ErrorDetail(
        error_code="AUTH_ERROR",
        error_message="Invalid API key",
        retry_eligible=False,
        suggestion="Check your API key configuration.",
    ),
).to_dict()
```

## API Reference

### `MCPServer`

```python
MCPServer(
    prefix: str,                         # Mandatory server prefix
    spooler: SpoolerConfig | None,       # Enable response spooling
    server_name: str | None = None,      # MCP server name (defaults to prefix)
)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `register(tool)` | Register a single tool |
| `register_all(tools)` | Register a list of tools |
| `run_stdio()` | Run on stdio transport |
| `run_http(host, port)` | Run on HTTP streamable transport |
| `run_sse(host, port)` | Run on SSE transport |

### `BaseTool`

```python
class MyTool(BaseTool):
    name: str               # Bare name (e.g. "get_devices")
    description: str        # Short description
    category: str           # Grouping key
    spooler_array_paths: list[str] | None = None
    spooler_auto_detect: bool = False
    InputModel: type[BaseModel] | None = None

    def guide(self) -> str: ...           # Usage guide with @placeholders
    async def execute(self, **params) -> dict: ...  # Tool logic
```

### `PrefixResolver`

```python
resolver = PrefixResolver("secops")
resolver.prefixed_name("get_devices")       # "secops_get_devices"
resolver.strip_prefix("secops_get_devices") # "get_devices"
resolver.resolve_placeholders("@get_devices") # "secops_get_devices"
resolver.set_instance_prefix("prod")        # Per-request override
```

## Requirements

- Python >= 3.12
- `mcp >= 1.25.0`
- `pydantic >= 2.0.0`
- `uvicorn >= 0.30.0` (optional, for HTTP/SSE transports)

## License

MIT
