# Tool Annotations

MCP lets a server describe how each tool behaves: whether it only reads,
whether it can destroy something, whether calling it twice is the same as
calling it once, and whether it reaches outside the server's own data.
Hosts use these hints to group tools and to decide how much to ask the user
before a call. spindl sends them from attributes on your tool class.

## Declaring annotations

```python
from typing import Any

from spindl import BaseTool, MCPServer


class ListDevices(BaseTool):
    name = "list_devices"
    description = "List monitored devices"
    category = "inventory"
    title = "List devices"
    read_only = True
    destructive = False
    idempotent = True
    open_world = False
    requires_reach = False  # this example serves no per-caller data

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": []}


class IsolateDevice(BaseTool):
    name = "isolate_device"
    description = "Cut a device off the network"
    category = "response"
    title = "Isolate device"
    read_only = False
    destructive = True
    idempotent = True
    open_world = True
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": {"isolated": True}}


server = MCPServer(prefix="secops")
server.register_all([ListDevices(), IsolateDevice()])
```

| Attribute | Sent as | Meaning |
|-----------|---------|---------|
| `title` | `title`, and `annotations.title` | A human-readable name for the tool |
| `read_only` | `annotations.readOnlyHint` | The tool does not change anything |
| `destructive` | `annotations.destructiveHint` | The tool may delete or overwrite something, rather than only add to it |
| `idempotent` | `annotations.idempotentHint` | Calling it again with the same arguments has no further effect |
| `open_world` | `annotations.openWorldHint` | The tool reaches outside the server's own domain (the internet, a third-party API) |

Every attribute defaults to `None`, meaning undeclared. `destructive` and
`idempotent` only mean something when `read_only` is not `True`. A tool
cannot be both read-only and destructive: registering one that declares
`read_only = True` and `destructive = True` raises `ValueError`.

`tools/list` then carries, for `list_devices`:

```json
{
  "name": "secops_list_devices",
  "title": "List devices",
  "description": "List monitored devices",
  "inputSchema": {"type": "object", "properties": {}},
  "annotations": {
    "title": "List devices",
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": false
  },
  "_meta": {"com.cognisn.spindl/category": "inventory"}
}
```

<!-- docs-test
async with docs_client(server) as client:
    listed = {tool["name"]: tool for tool in await client.list()}
assert listed["secops_list_devices"]["annotations"] == {
    "title": "List devices",
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
assert listed["secops_list_devices"]["title"] == "List devices"
assert listed["secops_list_devices"]["_meta"] == {"com.cognisn.spindl/category": "inventory"}
assert listed["secops_isolate_device"]["annotations"]["destructiveHint"] is True
-->

## How hosts use them

Hosts such as Claude Desktop group a connector's tools by `readOnlyHint` and
`destructiveHint`, and let the user set permissions per group: read-only
tools can be allowed freely while tools that write or delete ask first.
A tool that declares nothing lands in the stricter group.

Annotations are hints for the host and the user. spindl does not enforce
them, and they are not an access control: deciding who may call a tool is
the job of [authentication and tool access](authentication.md), and a tool
marked read-only must still be written so that it only reads. Clients are
told by the MCP specification to treat annotations from untrusted servers as
untrusted, so a wrong hint misleads honest users; it never grants anything.

## Undeclared hints

spindl sends only what you declare. When a hint is undeclared it is left out
of `tools/list`, and hosts apply the MCP specification's defaults:

| Hint | Default when not sent |
|------|-----------------------|
| `readOnlyHint` | `false`: the tool may change things |
| `destructiveHint` | `true`: the change may be destructive |
| `idempotentHint` | `false` |
| `openWorldHint` | `true` |

A tool declaring nothing is therefore treated as one that may destroy data,
which is the safe assumption and usually the wrong one. Declaring `False`
counts as declaring: `destructive = False` is sent as
`"destructiveHint": false`.

## The start-up warning

When the server starts, spindl logs one warning, on the `spindl.registry`
logger, naming every tool that declares neither `read_only` nor
`destructive`:

```text
2 tool(s) declare neither read_only nor destructive, so hosts treat them as possibly destructive: export_report, ping. Set read_only or destructive on each tool class.
```

```python
class Ping(BaseTool):
    name = "ping"
    description = "Health check"
    category = "meta"
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": "pong"}


class ExportReport(Ping):
    name = "export_report"
    description = "Export a report"


quiet_server = MCPServer(prefix="demo")
quiet_server.register_all([Ping(), ExportReport()])
```

<!-- docs-test
docs_log.clear()
async with docs_client(quiet_server) as client:
    listed = {tool["name"]: tool for tool in await client.list()}
assert "annotations" not in listed["demo_ping"] and "title" not in listed["demo_ping"]
assert docs_log == [
    "2 tool(s) declare neither read_only nor destructive, so hosts treat them as "
    "possibly destructive: export_report, ping. Set read_only or destructive on "
    "each tool class."
], docs_log
-->

The warning is logged once, after the built-in tools are registered, and
names tools by their bare names, sorted. It ignores who may see each tool.
Set `read_only` or `destructive` on each tool it names to silence it.

## Built-in tools

spindl's own tools (`list_tools`, `describe_tool`, and the `spooler_*` tools
when the spooler is enabled) declare themselves read-only, non-destructive,
idempotent and closed-world, with titles ("List tools", "Describe tool",
"List spools", "Query spool", "Aggregate spool", "Distinct spool values").

## category in _meta

A tool's `category` is sent in its `_meta` under the key
`com.cognisn.spindl/category`, available in code as
`spindl.registry.CATEGORY_META_KEY`. Nothing is sent for an empty category.
`category` remains the grouping used by the [skills guide](skills-guide.md)'s
`list_tools`, which also returns each tool's `title`, `read_only` and
`destructive`.

```python
from spindl.registry import CATEGORY_META_KEY

assert CATEGORY_META_KEY == "com.cognisn.spindl/category"
```
