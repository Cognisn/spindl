# Spindl Sample Server

A fictional "inventory" MCP server that demonstrates the core features of the
spindl framework.

## What it shows

| Feature | Where |
|---|---|
| **Tool registration** with `BaseTool` subclasses | `tools/get_devices.py`, `tools/get_vulnerabilities.py` |
| **Pydantic InputModel** for parameter validation | Every tool's `InputModel` class |
| **Custom guide()** with `@placeholder` references | Every tool's `guide()` method |
| **Spooler auto-detect** (find arrays automatically) | `GetDevicesTool.spooler_auto_detect = True` |
| **Explicit spooler_array_paths** | `GetVulnerabilitiesTool.spooler_array_paths = ["vulnerabilities"]` |
| **ResponseEnvelope** for consistent output | All tool `execute()` methods |
| **Transport selection** (stdio / HTTP / SSE) | `server.py` CLI arguments |

## Running

```bash
# From the project root
cd /path/to/spindl

# Install spindl in dev mode (if not already)
pip install -e ".[dev]"

# stdio (for Claude Desktop / MCP Inspector)
python sample/server.py

# HTTP streamable (requires pip install spindl[http])
python sample/server.py --http --port 8000

# SSE transport
python sample/server.py --sse --port 8000
```

## Tools exposed

All tool names on the wire are prefixed with `inventory_`:

| Wire name | Category | Description |
|---|---|---|
| `inventory_get_devices` | inventory | List devices with optional filtering |
| `inventory_get_vulnerabilities` | security | Retrieve vulnerability findings |
| `inventory_spooler_list` | spooler | List spooled data sets (auto-registered) |
| `inventory_spooler_query` | spooler | Query spooled data (auto-registered) |
| `inventory_spooler_aggregate` | spooler | Aggregate spooled data (auto-registered) |
| `inventory_spooler_distinct` | spooler | Distinct value counts (auto-registered) |
| `inventory_list_tools` | skills | List all tools (auto-registered) |
| `inventory_describe_tool` | skills | Describe a specific tool (auto-registered) |

## Spooler in action

`get_vulnerabilities` returns 80 records by default. With the sample
`SpoolerConfig` (max 5 inline items, 1000 max inline tokens), the
vulnerability array will be spooled to SQLite and replaced with a
summary containing:

- `spool_id` for follow-up queries
- Column schema and types
- Statistics (distinct counts, numeric ranges)
- 3 sample records

The LLM can then use `inventory_spooler_query` to filter, sort, and
paginate through the full dataset without overloading its context window.
