# Prefix System

Spindl's prefix system prevents tool name collisions when MCP clients connect to multiple servers. It uses a two-layer hierarchical approach.

## Overview

```
Wire name format:  {instance}_{server}_{tool}
                        │         │       │
                     optional   required  required
                    (runtime)   (code)
```

Examples:

| Instance | Server | Tool | Wire Name |
|----------|--------|------|-----------|
| *(none)* | `secops` | `list_devices` | `secops_list_devices` |
| `prod` | `secops` | `list_devices` | `prod_secops_list_devices` |
| `staging` | `secops` | `list_devices` | `staging_secops_list_devices` |

## Level 1: Server Prefix

Set in code by the developer. Mandatory. Cannot be changed at runtime.

```python
server = MCPServer(prefix="secops")
```

The prefix is normalised: lowercased, stripped, and trimmed of leading/trailing underscores.

```python
MCPServer(prefix="SecOps")    # → "secops"
MCPServer(prefix=" SecOps_ ") # → "secops"
```

An empty or whitespace-only prefix raises `ValueError`.

## Level 2: Instance Prefix

Optional. Set at runtime to distinguish multiple deployments of the same server.

### Via Environment Variable

```bash
export SPINDL_INSTANCE_PREFIX=prod
```

This applies to all requests for the server's lifetime.

### Via HTTP Header

```
X-Spindl-Prefix: staging
```

This applies per-request and takes **precedence over the environment variable**. Only available with HTTP/SSE transports.

### Precedence

1. HTTP header `X-Spindl-Prefix` (per-request, highest priority)
2. Environment variable `SPINDL_INSTANCE_PREFIX` (process-level)
3. No instance prefix (just the server prefix)

### Concurrency Isolation

The HTTP header value is stored in a `contextvars.ContextVar`, which provides per-async-task isolation. This means concurrent HTTP requests with different `X-Spindl-Prefix` headers are correctly isolated -- each request sees its own prefix.

## @Placeholder Syntax

Tool guides, descriptions, and spooler guidance text reference other tools using `@bare_name` placeholders.

### Writing Placeholders

```python
def guide(self) -> str:
    return (
        "Use @list_devices to get all devices. "
        "Query large results with @spooler_query. "
        "See @spooler_aggregate for grouping."
    )
```

### Resolution Rules

- Pattern: `@([a-z][a-z0-9_]*)` (lowercase letters, digits, underscores)
- Only **registered** tool names are replaced
- Unknown `@references` pass through untouched
- Resolution happens at **render time**, not registration time

### Resolution Example

With `prefix="secops"` and instance prefix `"prod"`:

| Input | Output |
|-------|--------|
| `@list_devices` | `prod_secops_list_devices` |
| `@spooler_query` | `prod_secops_spooler_query` |
| `@unknown_tool` | `@unknown_tool` *(unchanged)* |
| `email@example.com` | `email@example.com` *(not matched -- `example` contains `.`)* |

### Where Placeholders Are Resolved

1. **`describe_tool` output** -- when the LLM calls `describe_tool`, the guide text is resolved
2. **Spooler response JSON** -- `_spooler_meta.instructions` and `query_hint` fields
3. **All tool call JSON output** -- the server resolves placeholders in the full JSON response

## Use Cases

### Single Server, Single Client

The simplest case. Just set a server prefix:

```python
server = MCPServer(prefix="secops")
```

Tools: `secops_list_devices`, `secops_spooler_query`, etc.

### Multiple Servers, One Client

Each server has a unique prefix. No collisions:

```python
# Server A
MCPServer(prefix="secops")   # secops_list_devices
# Server B
MCPServer(prefix="dataeng")  # dataeng_list_devices
```

### Same Server, Multiple Instances

Deploy the same server twice with different instance prefixes:

```bash
# Production container
SPINDL_INSTANCE_PREFIX=prod python -m my_server

# Staging container
SPINDL_INSTANCE_PREFIX=staging python -m my_server
```

The MCP client sees:
- `prod_secops_list_devices`
- `staging_secops_list_devices`

### Per-Request Prefixing (HTTP)

For multi-tenant deployments where a single server process serves different contexts:

```bash
# Client A
curl -H "X-Spindl-Prefix: tenant_a" ...
# Tools appear as: tenant_a_secops_list_devices

# Client B
curl -H "X-Spindl-Prefix: tenant_b" ...
# Tools appear as: tenant_b_secops_list_devices
```

## PrefixResolver API

```python
from spindl import PrefixResolver

resolver = PrefixResolver("secops")

# Properties
resolver.server_prefix      # "secops"
resolver.instance_prefix    # str | None (from context var or env)
resolver.full_prefix        # "prod_secops" or "secops"
resolver.known_names        # frozenset of registered bare names

# Methods
resolver.prefixed_name("get_devices")           # "secops_get_devices"
resolver.strip_prefix("secops_get_devices")     # "get_devices"
resolver.strip_prefix("other_get_devices")      # None
resolver.resolve_placeholders("Use @get_devices") # "Use secops_get_devices"
resolver.register_known_name("get_devices")     # Register for @resolution
resolver.set_instance_prefix("prod")            # Set per-request prefix
resolver.set_instance_prefix(None)              # Clear per-request prefix
```
