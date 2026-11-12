# Spindl Sample Server

A fictional "inventory" MCP server that demonstrates the spindl framework,
including annotations, API key authentication and reach.

## What it shows

| Feature | Where |
|---|---|
| **Tool registration** with `BaseTool` subclasses | `tools/get_devices.py`, `tools/get_vulnerabilities.py`, `tools/acknowledge_finding.py` |
| **Annotations** (`title`, `read_only`, `destructive`, `idempotent`, `open_world`) | Every tool class |
| **Permissions** a caller needs (`inventory:read`, `inventory:write`) | Every tool's `permissions` |
| **API key authentication** with `ApiKeyAuthenticator` and `ScopeAuthoriser` | `server.py`, `build_server()` |
| **Reach applied inside every tool**, for reads and for the write | `tools/reach.py` and each tool's `execute()` |
| **Pydantic InputModel** for parameter validation | Every tool's `InputModel` class |
| **Custom guide()** with `@placeholder` references | Every tool's `guide()` method |
| **Spooler auto-detect** (find arrays automatically) | `GetDevicesTool.spooler_auto_detect = True` |
| **Explicit spooler_array_paths** | `GetVulnerabilitiesTool.spooler_array_paths = ["vulnerabilities"]` |
| **ResponseEnvelope** for consistent output | All tool `execute()` methods |
| **Transport selection** (stdio / HTTP / SSE / Flask) | `server.py` CLI arguments, `flask_app.py` |

## Running

```bash
# From the project root, in a virtual environment
pip install -e ".[http,wsgi]" flask

# stdio (for Claude Desktop / MCP Inspector); no authentication
python sample/server.py

# HTTP streamable at http://127.0.0.1:8000/mcp, with API keys
python sample/server.py --http --port 8000

# SSE at http://127.0.0.1:8000/sse, with API keys
python sample/server.py --sse --port 8000

# Mounted in a small Flask application, MCP at /mcp, with API keys
python sample/server.py --flask --port 8000
```

The networked modes listen on 127.0.0.1 unless you pass `--host`.

## API keys

On the networked transports the server generates two demo keys when it
starts and prints them to stderr (or writes them as JSON to the file named by
`--keys-file`). They are random, synthetic and valid only until the process
stops; nothing in this folder holds a key. Send one as the `X-API-Key`
header.

| Key | Tool permissions | Reach |
|---|---|---|
| reader | `inventory:read` | sites `us-east-1` and `eu-west-1`, read only |
| editor | `inventory:read`, `inventory:write` | every site, may write |

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: <the reader key printed at start-up>" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "inventory_get_devices", "arguments": {"limit": 5}}}'
```

A request without a key, or with a wrong one, gets `401`.

## Tool access is not reach

The two keys show both controls:

- **Tool access.** The reader lacks `inventory:write`, so
  `ScopeAuthoriser` refuses `acknowledge_finding` and spindl hides it from the
  reader's `tools/list`. That decision is made before any tool code runs.
- **Reach.** Both keys may call `get_devices`, but the reader sees only the
  devices at its two sites, because the tool filters by
  `self.context.reach` before anything else. `get_vulnerabilities` applies
  the same reach through each finding's device, and `acknowledge_finding`
  checks that the reach allows writing and covers the finding's site before
  it records anything. Passing the tool access check never limits what a
  tool touches; only the tool's own check does.

Over stdio there is no authentication and no credential, so the tools are
built with a local reach covering every site. See
[Authentication](../docs/authentication.md#tool-access-is-not-reach).

## Tools exposed

All tool names on the wire are prefixed with `inventory_`:

| Wire name | Category | Annotations | Permission |
|---|---|---|---|
| `inventory_get_devices` | inventory | read-only, idempotent | `inventory:read` |
| `inventory_get_vulnerabilities` | security | read-only, idempotent | `inventory:read` |
| `inventory_acknowledge_finding` | security | writes, not destructive, idempotent | `inventory:write` |
| `inventory_spooler_list` | spooler | read-only (auto-registered) | none |
| `inventory_spooler_query` | spooler | read-only (auto-registered) | none |
| `inventory_spooler_aggregate` | spooler | read-only (auto-registered) | none |
| `inventory_spooler_distinct` | spooler | read-only (auto-registered) | none |
| `inventory_list_tools` | skills | read-only (auto-registered) | none |
| `inventory_describe_tool` | skills | read-only (auto-registered) | none |

## Spooler in action

`get_vulnerabilities` returns up to 80 records. With the sample
`SpoolerConfig` (max 5 inline items, 1000 max inline tokens), the
vulnerability array will be spooled to SQLite and replaced with a
summary containing:

- `spool_id` for follow-up queries
- Column schema and types
- Statistics (distinct counts, numeric ranges)
- 3 sample records

The LLM can then use `inventory_spooler_query` to filter, sort, and
paginate through the full dataset without overloading its context window.
Spools are confined to the key's subject, and hold only what the tool
returned, so they respect the key's reach too.

## Tests

`tests/test_sample.py` starts this server over HTTP streamable and through
its Flask application, and calls its tools with the `mcp` client.
