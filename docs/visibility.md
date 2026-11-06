# Tool Visibility

This page described the 0.4 `tool_visibility` hook. In 0.5 the hook is
deprecated: deciding which tools a caller may see and call is the job of an
`Authenticator`'s `authorise()` method.

- [Authentication and Tool Access](authentication.md) describes the
  `Authenticator`, the `hide` and `step_up` denial modes, and why tool access
  is not reach.
- [Upgrading from 0.4](upgrading-0.5.md) shows a 0.4 `tool_visibility` hook
  still running through its adapter, and how to fold it into `authorise()`.

What 0.4 servers relied on still holds with the default `denial_mode="hide"`:
a tool the caller may not use is left out of `tools/list` and
`{prefix}_list_tools`, and `tools/call` and `{prefix}_describe_tool` answer
it exactly as an unknown tool.
