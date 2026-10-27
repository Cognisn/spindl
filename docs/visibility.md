# Tool Visibility

A server can decide, per request, which tools each caller may see. Pass a
`tool_visibility` hook to `MCPServer`:

```python
from mcp.server.auth.provider import AccessToken
from spindl import AuthConfig, BaseTool, MCPServer


def visible(identity: AccessToken | None, tool: BaseTool) -> bool:
    # Only the designated client may see the approval tool.
    if tool.name == "approve":
        return identity is not None and identity.client_id == designated_client_id()
    return True


server = MCPServer(
    prefix="tracker",
    auth=AuthConfig(...),
    tool_visibility=visible,
)
```

The hook receives the verified identity for the current request (the same
value `current_identity()` returns, or `None` when authentication is off)
and the tool, and returns whether that tool is visible.

## What it governs

The decision is made in one place, the `ToolRegistry`, so every path agrees:

| Path | A hidden tool |
|------|---------------|
| `tools/list` | is omitted |
| `tools/call` | is refused with exactly the `TOOL_NOT_FOUND` error an unregistered tool gets |
| `{prefix}_list_tools` | is not listed, and is not counted in `total_tools` |
| `{prefix}_describe_tool` | gets exactly the answer an unregistered tool gets |

Nothing in any response hints that a hidden tool exists. The hook sees
every tool, including the skills guide and spooler tools; they stay visible
unless the hook says otherwise.

## Writing a hook

- **Keep it quick and free of side effects.** It may be called several times
  in one request (once per tool when listing, again when calling).
- **It fails closed.** If the hook raises, the tool is hidden for that request
  and a warning is logged.
- **Re-check inside sensitive tools.** Visibility controls what a client sees
  and can call at that moment. A tool that must only run for a given caller
  should still check `current_identity()` in `execute`, because the policy
  behind the hook can change between a client listing tools and calling one.
- **With no hook, every tool is visible,** exactly as in earlier releases.

The hook is policy supplied by the consuming server. spindl itself does not
filter tools by any built-in rule (read-only modes and similar were removed in
0.1.x and remain out of scope).
