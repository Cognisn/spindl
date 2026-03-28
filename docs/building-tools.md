# Building Tools

This guide covers everything you need to know to build MCP tools with spindl.

## Tool Structure

Every spindl tool is a Python class that inherits from `BaseTool`:

```python
from spindl import BaseTool

class MyTool(BaseTool):
    # Required class attributes
    name = "my_tool"            # Bare name (no prefix)
    description = "What it does" # Short, one line
    category = "my_category"    # For skills guide grouping

    # Optional class attributes
    spooler_array_paths = None
    spooler_auto_detect = False
    InputModel = None            # Pydantic BaseModel subclass

    # Optional: override for rich guide text
    def guide(self) -> str: ...

    # Required: implement your logic
    async def execute(self, **params) -> dict: ...
```

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Tool name | `snake_case` | `list_devices`, `search_vulns` |
| Category | `snake_case` | `inventory`, `security`, `data_query` |
| Description | Sentence, no period | `List all monitored devices` |

Tool names must match the pattern `[a-z][a-z0-9_]*` for `@placeholder` resolution to work.

## Input Parameters

Define a Pydantic `InputModel` as an inner class to declare and validate tool parameters:

```python
from pydantic import BaseModel, Field

class QueryDevices(BaseTool):
    name = "query_devices"
    description = "Query device inventory with filters"
    category = "inventory"

    class InputModel(BaseModel):
        # Required parameter
        query: str = Field(
            description="KQL query string"
        )
        # Optional with default
        limit: int = Field(
            default=50,
            ge=1,
            le=500,
            description="Maximum results to return"
        )
        # Optional nullable
        severity: str | None = Field(
            default=None,
            description="Filter by severity level"
        )

    async def execute(self, **params) -> dict:
        validated = self.InputModel(**params)
        # Use validated.query, validated.limit, validated.severity
        ...
```

The `InputModel` automatically:
- Generates the MCP tool's JSON Schema (shown to the LLM)
- Validates input at execution time
- Provides default values for optional parameters

### Tools Without Parameters

Simply omit `InputModel`:

```python
class ListAll(BaseTool):
    name = "list_all"
    description = "List everything"
    category = "inventory"

    async def execute(self, **params) -> dict:
        return {"success": True, "data": [...]}
```

## Writing Guides

The `guide()` method returns detailed usage instructions that the LLM can request via the `describe_tool` skill.

### Default Guide

If you don't override `guide()`, spindl auto-generates documentation from the `InputModel` fields. This is functional but minimal.

### Custom Guide

Override `guide()` for rich documentation with examples:

```python
def guide(self) -> str:
    return (
        "# @query_devices\n\n"
        "Query the device inventory using KQL-style filters.\n\n"
        "## Parameters\n\n"
        "- **query** (required): KQL query string\n"
        "- **limit** (optional): Max results, 1-500 (default: 50)\n"
        "- **severity** (optional): Filter by severity\n\n"
        "## Examples\n\n"
        "### Find all Windows servers\n"
        '```json\n{"query": "OSPlatform == \'Windows\' and '
        'DeviceType == \'Server\'"}\n```\n\n'
        "### Search with limit\n"
        '```json\n{"query": "ExposureLevel == \'High\'", '
        '"limit": 100}\n```\n\n'
        "## Working with Large Results\n\n"
        "When results exceed the inline threshold, they are "
        "automatically spooled. Use @spooler_query to filter "
        "and paginate, @spooler_aggregate for grouping, or "
        "@spooler_distinct to explore column values.\n"
    )
```

### @Placeholder Syntax

Reference other tools using `@bare_name`:

```python
"Use @spooler_query to access the data."
"See @list_tools for all available tools."
"Call @describe_tool for detailed instructions."
```

These are resolved to fully prefixed wire names at render time. Only registered tool names are replaced -- unknown references pass through.

## Return Values

Tools should return a dictionary. Spindl provides optional response types for consistency:

### Success Response

```python
from spindl import ResponseEnvelope, ResponseMetadata

async def execute(self, **params) -> dict:
    items = await self.fetch_data()
    return ResponseEnvelope(
        success=True,
        data={"items": items},
        metadata=ResponseMetadata(
            total_results=len(items),
            returned_results=len(items),
        ),
    ).to_dict()
```

### Error Response

```python
from spindl import StructuredError, ErrorDetail

async def execute(self, **params) -> dict:
    try:
        result = await self.api_call()
        return {"success": True, "data": result}
    except AuthError as exc:
        return StructuredError(
            error=ErrorDetail(
                error_code="AUTH_ERROR",
                error_message=str(exc),
                retry_eligible=False,
                suggestion="Check your API credentials.",
            ),
        ).to_dict()
```

### Plain Dict

You can also return a plain dict -- there's no strict requirement to use the response types:

```python
async def execute(self, **params) -> dict:
    return {"success": True, "data": "pong"}
```

## Spooler Integration

### Explicit Array Paths

When you know which response fields contain arrays:

```python
class ListVulns(BaseTool):
    name = "list_vulns"
    description = "List vulnerabilities"
    category = "security"
    spooler_array_paths = ["results"]  # Spool data["results"]

    async def execute(self, **params) -> dict:
        vulns = await self.fetch_vulns()
        return {
            "success": True,
            "data": {
                "results": vulns,         # This array gets spooled
                "summary": {"total": len(vulns)},  # This stays inline
            },
        }
```

Dot notation for nested paths: `spooler_array_paths = ["data.items", "data.related"]`

### Auto-Detect

When the response structure varies:

```python
class FlexibleQuery(BaseTool):
    name = "flexible_query"
    description = "Run a flexible query"
    category = "data"
    spooler_auto_detect = True  # Spooler finds arrays automatically

    async def execute(self, **params) -> dict:
        result = await self.run_query()
        return {"success": True, "data": result}
```

The spooler scans the response up to 3 levels deep for arrays of objects that exceed the threshold.

### When Spooling Occurs

An array is spooled when **both** conditions are met:
1. The tool has `spooler_array_paths` set OR `spooler_auto_detect = True`
2. The array exceeds `max_inline_items` (default: 10) OR `max_inline_tokens` (default: 2000)

Small arrays are returned inline as normal.

## Dependency Injection

Unlike the original dtSecOpsMCPServer `BaseTool`, spindl's `BaseTool` has **no constructor injection** of clients, registries, or other dependencies. Tool authors manage their own dependencies:

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "Tool with dependencies"
    category = "data"

    def __init__(self, api_client: MyAPIClient) -> None:
        self._client = api_client

    async def execute(self, **params) -> dict:
        data = await self._client.fetch(...)
        return {"success": True, "data": data}

# Registration
client = MyAPIClient(api_key="...")
server.register(MyTool(api_client=client))
```

## Complete Example

```python
import asyncio
from pydantic import BaseModel, Field
from spindl import MCPServer, BaseTool, SpoolerConfig, ResponseEnvelope, ResponseMetadata

class SearchCVEs(BaseTool):
    name = "search_cves"
    description = "Search the CVE database for vulnerabilities"
    category = "vulnerability_management"
    spooler_array_paths = ["cves"]

    class InputModel(BaseModel):
        query: str = Field(description="Search keywords or CVE ID")
        severity: str | None = Field(
            default=None,
            description="Filter: critical, high, medium, low"
        )
        year: int | None = Field(
            default=None, ge=2000, le=2030,
            description="Filter by CVE year"
        )
        limit: int = Field(
            default=100, ge=1, le=1000,
            description="Maximum CVEs to return"
        )

    def guide(self) -> str:
        return (
            "# @search_cves\n\n"
            "Search the National Vulnerability Database for CVEs.\n\n"
            "## Parameters\n\n"
            "- **query** (required): Keywords or CVE ID (e.g. "
            "'CVE-2024-1234' or 'apache remote code execution')\n"
            "- **severity** (optional): critical, high, medium, low\n"
            "- **year** (optional): CVE year (2000-2030)\n"
            "- **limit** (optional): Max results (default: 100)\n\n"
            "## Examples\n\n"
            "### Search by keyword\n"
            '```json\n{"query": "log4j", "severity": "critical"}\n'
            "```\n\n"
            "### Search by CVE ID\n"
            '```json\n{"query": "CVE-2024-3094"}\n```\n\n'
            "## Working with Results\n\n"
            "Large result sets are automatically spooled. Use:\n"
            "- @spooler_query to filter and paginate\n"
            "- @spooler_aggregate to count by severity or vendor\n"
            "- @spooler_distinct to see affected products\n"
        )

    async def execute(self, **params) -> dict:
        validated = self.InputModel(**params)
        # Your search logic here
        cves = [
            {"cve_id": f"CVE-2024-{i}", "severity": "high", "score": 7.5}
            for i in range(validated.limit)
        ]
        return ResponseEnvelope(
            success=True,
            data={"cves": cves, "query": validated.query},
            metadata=ResponseMetadata(
                total_results=len(cves),
                returned_results=len(cves),
            ),
        ).to_dict()

server = MCPServer(
    prefix="vulndb",
    spooler=SpoolerConfig(max_inline_items=20),
)
server.register(SearchCVEs())
asyncio.run(server.run_stdio())
```
