# Response Spooler

The response spooler intercepts large array responses from tools and stores them in an ephemeral SQLite database. Instead of overwhelming the LLM's context window, the LLM receives a compact summary and uses query tools to explore the data on demand.

## How It Works

```
Tool returns 500 items
        │
        ▼
Spooler checks thresholds
  (max_inline_items: 10, max_inline_tokens: 2000)
        │
        ▼
Array exceeds threshold → store in SQLite
        │
        ▼
Return summary to LLM:
  - spool_id
  - total_records
  - column names and types
  - 3 sample records
  - statistics (distinct counts, numeric ranges)
  - query_hint
        │
        ▼
LLM uses spooler tools with spool_id to explore
```

## Enabling the Spooler

Pass a `SpoolerConfig` to the server:

```python
from spindl import MCPServer, SpoolerConfig

server = MCPServer(
    prefix="secops",
    spooler=SpoolerConfig(),  # Use defaults
)
```

This automatically registers 4 spooler query tools.

## Configuration

```python
SpoolerConfig(
    db_path="/tmp/mcp_spooler.db",  # SQLite file location
    max_inline_tokens=2000,          # Token estimate threshold
    max_inline_items=10,             # Array item count threshold
    default_page_size=20,            # Default records per page
    max_page_size=50,                # Hard ceiling on page size
    summary_sample_size=3,           # Records in summary sample
    chars_per_token=4,               # Character-to-token ratio
    db_cleanup_on_exit=True,         # Delete DB on shutdown
)
```

### Environment Variables

Every setting can be overridden with an environment variable:

| Setting | Env Var | Default |
|---------|---------|---------|
| `db_path` | `SPOOLER_DB_PATH` | `/tmp/mcp_spooler.db` |
| `max_inline_tokens` | `SPOOLER_MAX_INLINE_TOKENS` | `2000` |
| `max_inline_items` | `SPOOLER_MAX_INLINE_ITEMS` | `10` |
| `default_page_size` | `SPOOLER_DEFAULT_PAGE_SIZE` | `20` |
| `max_page_size` | `SPOOLER_MAX_PAGE_SIZE` | `50` |
| `summary_sample_size` | `SPOOLER_SUMMARY_SAMPLE_SIZE` | `3` |
| `db_cleanup_on_exit` | `SPOOLER_CLEANUP_ON_EXIT` | `true` |

## Tool Opt-In

Tools must explicitly opt in to spooling:

### Explicit Array Paths

```python
class ListDevices(BaseTool):
    spooler_array_paths = ["devices"]
    # data["devices"] will be checked and spooled if large
```

Supports dot notation for nested paths:

```python
spooler_array_paths = ["Results", "data.items", "response.records"]
```

### Auto-Detect

```python
class FlexibleTool(BaseTool):
    spooler_auto_detect = True
    # Spooler scans response for arrays of objects up to depth 3
```

Auto-detect finds arrays that:
- Contain at least one element
- Have dict elements (arrays of primitives are ignored)
- Are nested at most 3 levels deep

## Spooling Decision

An array is spooled when it exceeds **either** threshold:

- `max_inline_items` (default: 10) -- more items than this
- `max_inline_tokens` (default: 2000) -- estimated tokens exceed this

Token estimation: `len(json.dumps(array)) / chars_per_token`

Arrays below both thresholds are returned inline as normal.

## Summary Response

When spooling occurs, the tool response is restructured:

```json
{
  "response_data": {
    "scan_id": "abc",
    "scan_time": "2026-03-28T10:00:00Z"
  },
  "spooled_data": [
    {
      "spool_id": "a1b2c3d4e5f6",
      "source_array": "vulnerabilities",
      "total_records": 500,
      "columns": ["cve_id", "severity", "cvss_score", "vendor"],
      "column_types": {
        "cve_id": "TEXT",
        "severity": "TEXT",
        "cvss_score": "REAL",
        "vendor": "TEXT"
      },
      "statistics": {
        "distinct_value_counts": {
          "severity": 4,
          "vendor": 12
        },
        "numeric_ranges": {
          "cvss_score": {"min": 1.2, "max": 10.0}
        }
      },
      "sample_records": [
        {"cve_id": "CVE-2024-1000", "severity": "critical", ...},
        {"cve_id": "CVE-2024-1001", "severity": "high", ...},
        {"cve_id": "CVE-2024-1002", "severity": "medium", ...}
      ],
      "query_hint": "Use 'secops_spooler_query' with spool_id 'a1b2c3d4e5f6' ..."
    }
  ],
  "_spooler_meta": {
    "source_tool": "list_vulns",
    "total_spools": 1,
    "total_spooled_records": 500,
    "instructions": "Large arrays have been stored ... Use 'secops_spooler_query' ..."
  }
}
```

Non-array data (`response_data`) is preserved inline. Only the large arrays are replaced.

## Query Tools

### spooler_list

List all available spooled data sets. No parameters.

```json
{}
```

### spooler_query

Filter, sort, paginate, and search spooled records.

```json
{
  "spool_id": "a1b2c3d4e5f6",
  "filters": [
    {"column": "severity", "operator": "eq", "value": "critical"}
  ],
  "sort_by": "cvss_score",
  "sort_order": "desc",
  "page": 1,
  "page_size": 20,
  "columns": ["cve_id", "severity", "cvss_score"]
}
```

**Filter operators:** `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `not_like`, `is_null`, `is_not_null`, `in`

### spooler_aggregate

Group-by aggregation with summary functions.

```json
{
  "spool_id": "a1b2c3d4e5f6",
  "group_by": ["severity"],
  "aggregates": [
    {"function": "count", "column": "*", "alias": "total"},
    {"function": "avg", "column": "cvss_score", "alias": "avg_score"}
  ],
  "sort_by": "total",
  "sort_order": "desc"
}
```

**Functions:** `count`, `countdistinct`, `sum`, `avg`, `min`, `max`

> **count vs countdistinct:** `count(*)` counts rows. `countdistinct(vendor)` counts unique vendors. Use `countdistinct` when you need the number of distinct entities.

### spooler_distinct

Unique values and frequency counts for a column.

```json
{
  "spool_id": "a1b2c3d4e5f6",
  "column": "severity",
  "limit": 50
}
```

Returns values sorted by frequency (most common first).

## Data Flattening

The spooler automatically flattens nested objects using dot notation:

```json
{"device": {"id": 1, "os": {"name": "Windows", "version": "11"}}}
```

Becomes columns: `device.id`, `device.os.name`, `device.os.version`

Nested arrays within objects are JSON-serialised into TEXT columns.

## SQLite Internals

The spooler creates:

- `_spool_registry` -- metadata for each spooled array (spool_id, source_tool, columns, etc.)
- `_spool_stats` -- statistics (distinct counts, numeric ranges)
- `spool_{spool_id}` -- one dynamically created table per spooled array

All queries use parameterised SQL. Column names are validated against the registered schema.

The database uses WAL journal mode and NORMAL synchronous for performance.

## Lifecycle

1. **Initialise**: `await spooler.initialise()` -- creates SQLite file and schema
2. **Process**: `spooler.process_response(response, source_tool, array_paths)` -- stores arrays
3. **Query**: `QueryEngine(connection, config).query(spool_id, ...)` -- reads data
4. **Cleanup**: `await spooler.cleanup()` -- closes connection, optionally deletes file
