# Skills Guide

Spindl automatically registers two "skills guide" tools with every server. These allow the LLM to discover available tools and request detailed usage instructions on demand.

## Why Skills Guides?

MCP tool descriptions are sent to the LLM as part of the system prompt. Long descriptions consume context tokens on every request, even when the tool isn't relevant. Skills guides solve this by:

1. Keeping tool **descriptions** short (one line)
2. Making detailed **guides** available on demand via a tool call
3. Grouping tools by **category** for easy discovery

## Auto-Registered Tools

### list_tools

Lists the tools the caller may use, grouped by category, with each tool's
prefixed wire name, title, description, and its `read_only` and
`destructive` annotations (`null` when undeclared). On a server with
authentication, tools the caller may not use are left out (see
[Authentication](authentication.md)).

**Wire name:** `{prefix}_list_tools`

**Parameters:** None

**Example response:**

```json
{
  "success": true,
  "platform": "spindl",
  "data": {
    "total_tools": 8,
    "categories": {
      "inventory": [
        {
          "name": "secops_list_devices",
          "title": "List devices",
          "description": "List all monitored devices",
          "read_only": true,
          "destructive": false
        }
      ],
      "security": [
        {
          "name": "secops_search_vulns",
          "title": "Search vulnerabilities",
          "description": "Search vulnerability database",
          "read_only": true,
          "destructive": false
        }
      ],
      "skills": [
        {
          "name": "secops_describe_tool",
          "title": "Describe tool",
          "description": "Get detailed usage guide for a specific tool",
          "read_only": true,
          "destructive": false
        },
        {
          "name": "secops_list_tools",
          "title": "List tools",
          "description": "List all available tools with name, category, and description",
          "read_only": true,
          "destructive": false
        }
      ],
      "spooler": [
        {
          "name": "secops_spooler_aggregate",
          "title": "Aggregate spool",
          "description": "Aggregate spooled data with grouping and summary functions",
          "read_only": true,
          "destructive": false
        }
      ]
    }
  }
}
```

The `spooler` category lists `spooler_distinct`, `spooler_list` and
`spooler_query` in the same form; they are left out above for brevity.

<!-- docs-test
from typing import Any

from spindl import BaseTool, MCPServer, SpoolerConfig


class ListDevices(BaseTool):
    name = "list_devices"
    description = "List all monitored devices"
    category = "inventory"
    title = "List devices"
    read_only = True
    destructive = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": []}


class SearchVulns(ListDevices):
    name = "search_vulns"
    description = "Search vulnerability database"
    category = "security"
    title = "Search vulnerabilities"


guide_server = MCPServer(prefix="secops", spooler=SpoolerConfig())
guide_server.register_all([ListDevices(), SearchVulns()])
async with docs_client(guide_server) as client:
    _, listing = await client.call("secops_list_tools")
assert listing["data"]["total_tools"] == 8
assert listing["data"]["categories"]["inventory"] == [
    {
        "name": "secops_list_devices",
        "title": "List devices",
        "description": "List all monitored devices",
        "read_only": True,
        "destructive": False,
    }
]
assert [t["name"] for t in listing["data"]["categories"]["skills"]] == [
    "secops_describe_tool",
    "secops_list_tools",
]
assert listing["data"]["categories"]["spooler"][0]["title"] == "Aggregate spool"
assert len(listing["data"]["categories"]["spooler"]) == 4
await guide_server._cleanup()
-->

### describe_tool

Returns the detailed usage guide for a specific tool, with all `@placeholders` resolved to prefixed wire names.

**Wire name:** `{prefix}_describe_tool`

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `tool_name` | Yes | The full wire name of the tool (as shown by `list_tools`) |

**Example call:**

```json
{"tool_name": "secops_search_vulns"}
```

**Example response:**

```json
{
  "success": true,
  "tool_name": "secops_search_vulns",
  "guide": "# secops_search_vulns\n\nSearch the vulnerability database...\n\nUse secops_spooler_query to filter results..."
}
```

Note how `@spooler_query` in the original guide text has been resolved to `secops_spooler_query`.

## Categories

Categories are declared per-tool via the `category` attribute:

```python
from spindl import BaseTool

class MyTool(BaseTool):
    category = "inventory"
```

The `list_tools` response groups tools by category. Choose consistent, descriptive categories:

| Category | Usage |
|----------|-------|
| `inventory` | Device/asset listing and search |
| `security` | Vulnerability and threat tools |
| `incident` | Alert and incident management |
| `data_query` | Generic data exploration |
| `spooler` | Spooler query tools (auto-assigned) |
| `skills` | Skills guide tools (auto-assigned) |
| `meta` | Server administration tools |

## LLM Workflow

A typical LLM interaction with skills guides:

1. **LLM calls `list_tools`** to see what's available
2. **LLM identifies a relevant tool** from the categorised list
3. **LLM calls `describe_tool`** to get the detailed guide
4. **LLM calls the actual tool** with the correct parameters
5. If the result is spooled, **LLM uses spooler tools** to explore

This pattern is efficient because the detailed guide is only fetched when needed, keeping the base context lean.

## Writing Good Guides

### Structure

```python
def guide(self) -> str:
    return (
        "# @tool_name\n\n"              # Title with placeholder
        "Description of what the tool does and when to use it.\n\n"
        "## Parameters\n\n"
        "- **param1** (required): What it does\n"
        "- **param2** (optional): What it does (default: value)\n\n"
        "## Examples\n\n"
        "### Use case 1\n"
        '```json\n{"param1": "value"}\n```\n\n'
        "## Working with Results\n\n"
        "Cross-reference other tools using @placeholders:\n"
        "- @spooler_query for filtering\n"
        "- @spooler_aggregate for grouping\n"
    )
```

<!-- docs-test
from spindl import PrefixResolver

structure_resolver = PrefixResolver("secops")
for known in ("tool_name", "spooler_query", "spooler_aggregate"):
    structure_resolver.register_known_name(known)
rendered = structure_resolver.resolve_placeholders(guide(None))
assert rendered.startswith("# secops_tool_name\n")
assert "- secops_spooler_query for filtering" in rendered
-->

### Tips

- **Start with `@tool_name`** in the title so the LLM sees the full prefixed name
- **Include concrete JSON examples** -- LLMs are much better at following examples than abstract descriptions
- **Cross-reference related tools** using `@placeholders` so the LLM knows the workflow
- **Explain when to use the tool** not just what it does
- **Keep it concise** -- guides are fetched on demand but still consume context tokens
