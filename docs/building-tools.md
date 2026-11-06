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

    # Annotations: how the tool behaves (see docs/annotations.md)
    title = "My tool"           # Human-readable name
    read_only = True            # Declare read_only or destructive on every tool
    destructive = False
    idempotent = None           # None means undeclared
    open_world = None

    # Tool access and reach (see docs/authentication.md)
    permissions = []            # Permissions a caller needs, e.g. ["devices:read"]
    requires_reach = None       # None: required when an Authenticator is configured

    # Optional class attributes
    spooler_array_paths = None
    spooler_auto_detect = False
    InputModel = None            # Pydantic BaseModel subclass
    reject_unknown_arguments = True

    # Optional: override for rich guide text
    def guide(self) -> str: ...

    # Required: implement your logic
    async def execute(self, **params) -> dict: ...
```

### Attributes Reference

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `""` | Bare tool name (required) |
| `description` | `str` | `""` | Short one-line description (required) |
| `category` | `str` | `""` | Grouping key for the skills guide, also sent in `_meta` |
| `title` | `str \| None` | `None` | Human-readable name, sent as `title` and `annotations.title` |
| `read_only` | `bool \| None` | `None` | Sent as `readOnlyHint` |
| `destructive` | `bool \| None` | `None` | Sent as `destructiveHint` |
| `idempotent` | `bool \| None` | `None` | Sent as `idempotentHint` |
| `open_world` | `bool \| None` | `None` | Sent as `openWorldHint` |
| `permissions` | `list[str]` | `[]` | Permissions (OAuth scope tokens) a caller needs; published as `scopes_supported` |
| `requires_reach` | `bool \| None` | `None` | Whether the tool needs the caller's reach; `None` means required when an `Authenticator` is configured |
| `spooler_array_paths` | `list[str] \| None` | `None` | Dot-notation paths to arrays to spool |
| `spooler_auto_detect` | `bool` | `False` | Auto-detect large arrays in the response |
| `InputModel` | `type[BaseModel] \| None` | `None` | Pydantic model for input validation |
| `reject_unknown_arguments` | `bool` | `True` | Reject arguments not declared by `InputModel` |

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Tool name | `snake_case` | `list_devices`, `search_vulns` |
| Category | `snake_case` | `inventory`, `security`, `data_query` |
| Description | Sentence, no period | `List all monitored devices` |
| Title | Short, sentence case | `List devices` |
| Permission | Lower case, `area:action` | `devices:read`, `devices:isolate` |

Tool names must match the pattern `[a-z][a-z0-9_]*` for `@placeholder` resolution to work.

## Annotations

Declare `read_only` or `destructive` on every tool. Hosts such as Claude
Desktop group tools by these hints, and a tool declaring neither is treated
as possibly destructive; spindl logs a warning at start-up naming each such
tool. Only declared hints are sent. See [Annotations](annotations.md).

## Permissions, Reach and the Call's Context

On a server with authentication, two things decide what a call does:

- **Tool access.** `permissions` names what a caller needs to use the tool.
  The server's `Authenticator` decides in `authorise()`, before your code
  runs, whether the caller may list and call it.
- **Reach.** What a permitted call may touch: which tenants, accounts,
  collections or hosts. It arrives as `self.context.reach`, and **your tool
  must apply it to every read and write it makes**. Being allowed to call the
  tool never limits what the tool touches.

`self.context` is a read-only `ToolContext` with the call's `identity`,
`reach` and `instance_prefix`, private to each call and `None` outside one:

```python
from typing import Any

from pydantic import BaseModel, Field

SITES = {"site-a": ["dev-1", "dev-2"], "site-b": ["dev-3"], "site-c": ["dev-4"]}


class ListSiteDevices(BaseTool):
    name = "list_site_devices"
    description = "List the devices at the caller's sites"
    category = "inventory"
    title = "List site devices"
    read_only = True
    destructive = False
    permissions = ["devices:read"]

    async def execute(self, **params: Any) -> dict[str, Any]:
        self.validate_input(params)
        reach = self.context.reach if self.context else None
        if not isinstance(reach, frozenset):  # this server's reach: a set of site names
            return {"success": False, "error": "no site reach"}
        devices = {site: SITES[site] for site in sorted(reach) if site in SITES}
        return {"success": True, "data": devices}
```

<!-- docs-test
from spindl import AuthConfig, Credentials, Identity, MCPServer


class SitesAuthenticator:
    async def authenticate(self, credentials: Credentials) -> Identity | None:
        if credentials.bearer_token != docs_token:
            return None
        return Identity(subject="ops", tool_permissions={"devices:read"}, reach=frozenset({"site-a", "site-c"}))

    async def authorise(self, identity, tool, action) -> bool:
        return set(tool.permissions) <= identity.tool_permissions


import secrets

docs_token = secrets.token_urlsafe(32)
sites_server = MCPServer(
    prefix="ops",
    auth=AuthConfig(
        authenticator=SitesAuthenticator(),
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
    ),
)
sites_server.register(ListSiteDevices())
async with docs_client(sites_server) as client:
    _, devices = await client.call(
        "ops_list_site_devices", {}, {"Authorization": f"Bearer {docs_token}"}
    )
assert devices["data"] == {"site-a": ["dev-1", "dev-2"], "site-c": ["dev-4"]}
-->

With an `Authenticator` configured, spindl refuses to run a tool that
requires reach when the caller's credential carries none (`REACH_REQUIRED`).
A tool that touches nothing caller-specific sets `requires_reach = False`.
[Authentication](authentication.md#tool-access-is-not-reach) works through a
full example.

## Input Parameters

Define a Pydantic `InputModel` as an inner class to declare and validate tool parameters:

```python
class QueryDevices(BaseTool):
    name = "query_devices"
    description = "Query device inventory with filters"
    category = "inventory"
    read_only = True
    destructive = False

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
        validated = self.validate_input(params)
        # Use validated.query, validated.limit, validated.severity
        return {"success": True, "data": {"query": validated.query, "limit": validated.limit}}
```

<!-- docs-test
result = await QueryDevices().execute(query="OSPlatform == 'Linux'")
assert result == {"success": True, "data": {"query": "OSPlatform == 'Linux'", "limit": 50}}
assert QueryDevices().input_schema["required"] == ["query"]
-->

The `InputModel` automatically:
- Generates the MCP tool's JSON Schema (shown to the LLM)
- Validates input at execution time
- Provides default values for optional parameters

`validate_input()` applies the model's field constraints and rejects any
argument the model does not declare, raising `ToolInputError`. Calling
`self.InputModel(**params)` directly still works, but skips the
unknown-argument check.

### Tools Without Parameters

Simply omit `InputModel`:

```python
class ListAll(BaseTool):
    name = "list_all"
    description = "List everything"
    category = "inventory"
    read_only = True
    destructive = False

    async def execute(self, **params) -> dict:
        self.validate_input(params)
        return {"success": True, "data": []}
```

A tool with no `InputModel` accepts no arguments at all, so any argument
passed to it is rejected.

## Argument Validation

Spindl tools reject arguments they do not declare. An unknown argument
returns a structured error naming both the rejected keys and the accepted
ones:

```json
{
  "success": false,
  "platform": "spindl",
  "error": {
    "error_code": "INVALID_ARGUMENTS",
    "error_message": "Tool 'query_devices' does not accept the argument(s) 'sort_by'. They were not applied.",
    "retry_eligible": true,
    "suggestion": "Accepted parameters: limit, query, severity. Remove the rejected argument(s) and call the tool again, or use a tool that supports them."
  }
}
```

<!-- docs-test
from spindl import ToolInputError

try:
    QueryDevices().validate_input({"query": "x", "sort_by": "name"})
except ToolInputError as exc:
    rejected = exc.to_dict()
assert rejected["error"]["error_message"] == (
    "Tool 'query_devices' does not accept the argument(s) 'sort_by'. They were not applied."
)
assert rejected["error"]["suggestion"].startswith("Accepted parameters: limit, query, severity.")
-->

The check runs at the MCP boundary in `MCPServer._handle_call_tool`, before
`execute()`, so a tool gets the protection whether or not it calls
`validate_input()` itself. Calling `validate_input()` in `execute()` as well
extends it to direct calls in tests and embedded use.

This is a correctness measure, not tidiness. A model that generalises across
a server's schema will eventually pass one tool's parameter to a sibling
that does not accept it. Silently dropping it produces a plausible answer to
a different question, which the model then reports as fact; an explicit
error is recovered from in one turn.

### Opting Out

A tool that deliberately takes free-form arguments can turn the check off:

```python
class Passthrough(BaseTool):
    name = "passthrough"
    description = "Forward arbitrary arguments to an upstream API"
    category = "integration"
    open_world = True
    reject_unknown_arguments = False
```

This is the exception. Prefer declaring the parameters.

### Handling the Error

`validate_input()` raises `ToolInputError`, which renders itself as the
structured error above:

```python
from spindl import ToolInputError

class CarefulQuery(QueryDevices):
    async def execute(self, **params) -> dict:
        try:
            validated = self.validate_input(params)
        except ToolInputError as exc:
            return exc.to_dict()
        return {"success": True, "data": {"query": validated.query}}
```

<!-- docs-test
answer = await CarefulQuery().execute(query="x", colour="blue")
assert answer["error"]["error_code"] == "INVALID_ARGUMENTS"
-->

Letting it propagate is also fine: the server catches it and returns the
same payload.

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

<!-- docs-test
QueryDevices.guide = guide
assert QueryDevices().guide().startswith("# @query_devices")
-->

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

class ListItems(BaseTool):
    name = "list_items"
    description = "List items"
    category = "inventory"
    read_only = True
    destructive = False

    async def fetch_data(self) -> list[dict]:
        return [{"id": 1}, {"id": 2}]

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

<!-- docs-test
listed = await ListItems().execute()
assert listed["success"] is True and listed["data"]["items"] == [{"id": 1}, {"id": 2}]
assert listed["metadata"]["total_results"] == 2
-->

### Error Response

```python
from spindl import StructuredError, ErrorDetail

class AuthError(Exception):
    """Raised by your API client when the upstream refuses its credentials."""

class CallUpstream(BaseTool):
    name = "call_upstream"
    description = "Call the upstream API"
    category = "integration"
    read_only = True
    destructive = False
    open_world = True

    async def api_call(self) -> dict:
        raise AuthError("upstream refused the API key")

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

<!-- docs-test
failed = await CallUpstream().execute()
assert failed["success"] is False and failed["error"]["error_code"] == "AUTH_ERROR"
-->

### Plain Dict

You can also return a plain dict -- there's no strict requirement to use the response types:

```python
class Ping(BaseTool):
    name = "ping"
    description = "Health check"
    category = "meta"
    read_only = True
    destructive = False
    requires_reach = False

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
    read_only = True
    destructive = False
    spooler_array_paths = ["results"]  # Spool data["results"]

    async def fetch_vulns(self) -> list[dict]:
        return [{"cve_id": f"CVE-2026-{i:04d}", "severity": "high"} for i in range(50)]

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

<!-- docs-test
from spindl import SpoolerConfig

spooled_server = MCPServer(prefix="vulndb", spooler=SpoolerConfig(max_inline_items=10))
spooled_server.register(ListVulns())
async with docs_client(spooled_server) as client:
    _, spooled = await client.call("vulndb_list_vulns")
assert spooled["data"]["spooled_data"][0]["total_records"] == 50
assert spooled["data"]["response_data"]["summary"] == {"total": 50}
await spooled_server._cleanup()
-->

### Auto-Detect

When the response structure varies:

```python
class FlexibleQuery(BaseTool):
    name = "flexible_query"
    description = "Run a flexible query"
    category = "data"
    read_only = True
    destructive = False
    spooler_auto_detect = True  # Spooler finds arrays automatically

    async def run_query(self) -> dict:
        return {"rows": [{"n": n} for n in range(3)]}

    async def execute(self, **params) -> dict:
        result = await self.run_query()
        return {"success": True, "data": result}
```

The spooler scans the response up to 3 levels deep for arrays of objects that exceed the threshold.

### When Spooling Occurs

An array is spooled when **both** conditions are met:
1. The tool has `spooler_array_paths` set OR `spooler_auto_detect = True`
2. The array exceeds `max_inline_items` (default: 10) OR `max_inline_tokens` (default: 2000)

Small arrays are returned inline as normal. On an authenticated server,
spools are confined to the caller's subject; see
[Response Spooler](spooler.md#scope).

## Dependency Injection

Unlike the original dtSecOpsMCPServer `BaseTool`, spindl's `BaseTool` has **no constructor injection** of clients, registries, or other dependencies. Tool authors manage their own dependencies:

<!-- docs-test
class MyAPIClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def fetch(self, *args: Any) -> list[str]:
        return ["record"]


server = MCPServer(prefix="data")
-->

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "Tool with dependencies"
    category = "data"
    read_only = True
    destructive = False

    def __init__(self, api_client: MyAPIClient) -> None:
        self._client = api_client

    async def execute(self, **params) -> dict:
        data = await self._client.fetch()
        return {"success": True, "data": data}

# Registration
client = MyAPIClient(api_key="...")  # read the real key from your secret store
server.register(MyTool(api_client=client))
```

<!-- docs-test
assert await MyTool(api_client=client).execute() == {"success": True, "data": ["record"]}
-->

## Complete Example

```python
import asyncio
from pydantic import BaseModel, Field
from spindl import MCPServer, BaseTool, SpoolerConfig, ResponseEnvelope, ResponseMetadata

class SearchCVEs(BaseTool):
    name = "search_cves"
    description = "Search the CVE database for vulnerabilities"
    category = "vulnerability_management"
    title = "Search CVEs"
    read_only = True
    destructive = False
    idempotent = True
    open_world = True          # queries an external database
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
        validated = self.validate_input(params)
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
