# Upgrading from 0.4

spindl 0.5 keeps 0.4 servers running: the 0.4 authentication interfaces
still work through adapters, and every name the 0.4 `spindl.auth` module
exported still imports. Most servers need only a dependency update and a
few tool attributes. Moving to the new `Authenticator` is the larger step,
and it changes one default on purpose: tools then require reach.

Work through the sections in order.

## 1. Dependencies and protocol

| | 0.4 | 0.5 |
|---|-----|-----|
| Python | 3.10 or later | 3.10 or later |
| `mcp` SDK | 1.25 or later, below 3 (1.x and 2.x) | **2.3 or later, below 3** |
| MCP protocol | as negotiated by the SDK | **2026-07-28** on every transport |
| Direct dependencies | `mcp`, `pydantic` | `mcp`, `pydantic`, `starlette`, `pyjwt[crypto]` |
| Extras | `http` (uvicorn) | `http` (uvicorn), **`wsgi`** (a2wsgi) |

- spindl 0.5 no longer runs on the `mcp` 1.x SDK. Pin `mcp>=2.3,<3` if your
  project pins it at all.
- spindl speaks protocol revision 2026-07-28 and still answers clients that
  use the earlier `initialize` handshake, so existing clients keep working.
- `starlette` and `pyjwt[crypto]` are now declared directly, at the versions
  `mcp` 2.3 already requires, so no new packages are installed.
- The new `wsgi` extra installs `a2wsgi` for serving from Flask, Django and
  other WSGI applications (see [Transports](transports.md#wsgi-flask-django-and-other-wsgi-servers)).

```bash
pip install --upgrade "cognisn-spindl[http]"          # ASGI and uvicorn
pip install --upgrade "cognisn-spindl[http,wsgi]"     # plus the WSGI bridge
```

**SSE clients.** With `mcp` 2.x the SDK handles each SSE request in the
context of the messages `POST` that carried it, so a client using
`X-Spindl-Prefix` must send the header on the `POST`s to the messages
endpoint as well as on the `GET` that opens the stream. A prefix sent only
on the `GET` no longer applies to tool calls.

## 2. Declare tool annotations

0.5 sends MCP tool annotations from new `BaseTool` attributes: `title`,
`read_only`, `destructive`, `idempotent` and `open_world`. Hosts such as
Claude Desktop group tools by them. A tool declaring neither `read_only` nor
`destructive` is treated by hosts as possibly destructive, and spindl logs
one warning at start-up naming every such tool:

```text
3 tool(s) declare neither read_only nor destructive, so hosts treat them as possibly destructive: export, list_devices, search. Set read_only or destructive on each tool class.
```

Silence it by declaring the hints on each tool it names:

```python
from typing import Any

from spindl import BaseTool


class ListDevices(BaseTool):
    name = "list_devices"
    description = "List monitored devices"
    category = "inventory"
    title = "List devices"   # new in 0.5
    read_only = True         # new in 0.5
    destructive = False      # new in 0.5

    async def execute(self, **params: Any) -> dict[str, Any]:
        return {"success": True, "data": []}
```

Registering a tool with both `read_only = True` and `destructive = True`
now raises `ValueError`. See [Annotations](annotations.md).

## 3. The auth package

`spindl.auth` is now a package. Every 0.4 name (`AuthConfig`,
`TokenVerifier`, `current_identity`, `protect`, `metadata_routes`,
`METADATA_PATH`, `_metadata_url`) still imports from it, so 0.4 imports
need no change. New names live beside them:

```python
from spindl import AuthConfig, Authenticator, Credentials, Identity, ToolContext
from spindl.auth import (
    ApiKeyAuthenticator,
    JwtAuthenticator,
    ScopeAuthoriser,
    TokenVerifier,  # the 0.4 protocol, kept
    current_identity,
    metadata_routes,
    protect,
)
```

## 4. Your 0.4 authentication still works, with a warning

A 0.4 server keeps its 0.4 behaviour exactly. Both 0.4 interfaces are
wrapped in adapters, and each logs one deprecation warning:

- `AuthConfig(token_verifier=...)`: "AuthConfig(token_verifier=...) is
  deprecated and will be removed in a future release. Implement
  spindl.auth.Authenticator and pass AuthConfig(authenticator=...)."
- `MCPServer(tool_visibility=...)`: "MCPServer(tool_visibility=...) is
  deprecated and will be removed in a future release. Decide tool access in
  spindl.auth.Authenticator.authorise()."

This 0.4 server runs unchanged on 0.5:

```python
from mcp.server.auth.provider import AccessToken

from spindl import AuthConfig, MCPServer, current_identity


class MyVerifier:
    """0.4: verifies a token against your authorisation server."""

    def __init__(self, valid: dict[str, AccessToken]) -> None:
        self._valid = valid

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._valid.get(token)


def visible(identity: AccessToken | None, tool: BaseTool) -> bool:
    """0.4: hide the export tool from everyone but the reporting client."""
    if tool.name == "export":
        return identity is not None and identity.client_id == "reporting"
    return True


class Export(BaseTool):
    name = "export"
    description = "Export everything"
    category = "reports"
    read_only = True
    destructive = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        identity = current_identity()
        return {"success": True, "data": {"scopes": identity.scopes if identity else []}}
```

<!-- docs-test
import secrets

reporting_token = secrets.token_urlsafe(32)
other_token = secrets.token_urlsafe(32)
verifier = MyVerifier(
    {
        reporting_token: AccessToken(token=reporting_token, client_id="reporting", scopes=["read"]),
        other_token: AccessToken(token=other_token, client_id="dashboard", scopes=["read"]),
    }
)
docs_log.clear()
legacy = MCPServer(
    prefix="secops",
    auth=AuthConfig(
        token_verifier=verifier,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
    ),
    tool_visibility=visible,
)
legacy.register_all([ListDevices(), Export()])
assert any(message.startswith("AuthConfig(token_verifier=...) is deprecated") for message in docs_log)
assert any(message.startswith("MCPServer(tool_visibility=...) is deprecated") for message in docs_log)
async with docs_client(legacy) as client:
    seen = {t["name"] for t in await client.list({"Authorization": f"Bearer {other_token}"})}
    _, exported = await client.call("secops_export", {}, {"Authorization": f"Bearer {reporting_token}"})
    # 0.4 behaviour: no reach requirement on the adapter path.
    _, listed = await client.call("secops_list_devices", {}, {"Authorization": f"Bearer {other_token}"})
assert "secops_export" not in seen and "secops_list_devices" in seen
assert exported["data"] == {"scopes": ["read"]}
assert listed["success"] is True
-->

`current_identity()` now returns an `Identity`. Under `token_verifier` it is
an `AccessTokenIdentity`, which keeps the 0.4 `scopes`, `token`, `resource`
and `claims` attributes, so code reading `current_identity().scopes` keeps
working. Two details changed: `subject` falls back to the token's
`client_id` when the token has none (it was `None`), and new code should read
`tool_permissions` rather than `scopes`.

The 0.4 interfaces cannot be combined with an `Authenticator`:
`AuthConfig` refuses `authenticator` together with `token_verifier`, and
`MCPServer` refuses `tool_visibility` together with an `authenticator`
(both `ValueError`).

## 5. Moving to an Authenticator

Fold the verifier and the visibility hook into one `Authenticator`:
`authenticate()` does what `verify_token` did and returns an `Identity`;
`authorise()` does what the visibility hook did, but receives the
`Identity`.

```python
from spindl.auth import ToolAction


class MyAuthenticator:
    def __init__(self, verifier: MyVerifier) -> None:
        self._verifier = verifier

    async def authenticate(self, credentials: Credentials) -> Identity | None:
        if credentials.bearer_token is None:
            return None
        access = await self._verifier.verify_token(credentials.bearer_token)
        if access is None:
            return None
        return Identity(
            subject=access.subject or access.client_id,
            client_id=access.client_id,
            tool_permissions=access.scopes,
            reach=reach_for(access.client_id),  # new: what this caller may touch
            expires_at=access.expires_at,
        )

    async def authorise(self, identity: Identity, tool: BaseTool, action: ToolAction) -> bool:
        if tool.name == "export":
            return identity.client_id == "reporting"
        return True


def reach_for(client_id: str) -> frozenset[str] | None:
    """The sites each client may see. None: no reach."""
    return {"reporting": frozenset({"site-a", "site-b"})}.get(client_id)


server = MCPServer(
    prefix="secops",
    auth=AuthConfig(
        authenticator=MyAuthenticator(verifier),
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
    ),
)
server.register_all([ListDevices(), Export()])
```

Your authenticator now owns audience binding: check that the token was
issued for this server's `resource_server_url`. If your tokens are JWTs
from an external authorisation server, `JwtAuthenticator` does all of this
for you, and `ApiKeyAuthenticator` covers API keys. See
[Authentication](authentication.md#reference-implementations).

### Reach is now required: the one deliberate change

With an `Authenticator` configured directly, **every tool requires reach**
unless it sets `requires_reach = False`. A call whose identity carries no
reach (`Identity.reach is None`) is refused with `REACH_REQUIRED` before any
tool code runs. The adapters in section 4 leave this off, so nothing changes
until you move.

When you move, for each tool either:

- return reach from `authenticate()` and apply `self.context.reach` to every
  read and write the tool makes (see
  [Tool access is not reach](authentication.md#tool-access-is-not-reach)), or
- set `requires_reach = False` on a tool that touches nothing caller-specific.

<!-- docs-test
async with docs_client(server) as client:
    _, refused = await client.call("secops_list_devices", {}, {"Authorization": f"Bearer {other_token}"})
    _, allowed = await client.call("secops_list_devices", {}, {"Authorization": f"Bearer {reporting_token}"})
assert refused["error"]["error_code"] == "REACH_REQUIRED"  # dashboard has no reach
assert allowed["success"] is True
-->

Passing `authorise()` never limits what a tool touches. In 0.4 a visibility
hook was easy to mistake for a data boundary; in 0.5 the two are named
separately so that the tool's own check is not forgotten.

### stdio with an Authenticator

stdio carries no credentials, so a server with an `Authenticator` run over
stdio has no identity. `authorise()` is not called and only tools with
`requires_reach = False` run. Serve stdio without `auth`, as in 0.4, if a
local user needs the full tool set.

## 6. ToolRegistry lookups

If your code calls `ToolRegistry` directly: on a server with an
authenticator or a visibility hook, the synchronous `get_tool()`,
`get_mcp_tool_definitions()`, `get_tool_guide()` and `list_tools_metadata()`
raise `RuntimeError`, because they cannot apply the per-caller access
decision. Use the asynchronous `listed_tools()`, `tool_definitions()`,
`tool_guide()` and `tools_metadata()`, which apply it, or `lookup()` when
you need a tool by wire name regardless of access. Servers without either
are unaffected.

## 7. What else is new

- [Annotations](annotations.md) on every tool, with the category in `_meta`.
- An [Authenticator](authentication.md) with `credential_headers`,
  `denial_mode="step_up"`, `BaseTool.permissions` published as
  `scopes_supported`, and `self.context` in tools.
- Reference `ApiKeyAuthenticator`, `ScopeAuthoriser` and
  `JwtAuthenticator`.
- `server.wsgi_app()` and `spindl.wsgi.init_app()` for
  [WSGI hosts](transports.md#wsgi-flask-django-and-other-wsgi-servers).
