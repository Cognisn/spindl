# Authentication and Tool Access

spindl can require every caller of the HTTP streamable, SSE and WSGI
transports to authenticate, decide which tools each caller may see and call,
and hand each tool the caller's identity and reach. This page covers all of
it. If you are moving a 0.4 server across, read
[Upgrading from 0.4](upgrading-0.5.md) as well.

## spindl is a resource server only

spindl checks credentials that something else issued. In OAuth 2.1 terms it
is a **resource server**: it never logs anyone in, never asks for consent,
never registers clients and never issues tokens or keys. Those stay with
your authorisation server, identity provider or key management process.
spindl's part is to read the credential from each request, ask your
`Authenticator` who the caller is, answer `401` and `403` with the right
challenges, publish the RFC 9728 protected-resource metadata, and filter
tools.

stdio carries no credentials; see [stdio](#stdio) below.

## Tool access is not reach

Read this section before writing any tool for an authenticated server. Two
separate controls come from every credential:

| Control | Question it answers | Decided by | Enforced by |
|---------|--------------------|------------|-------------|
| **Tool access** | May this caller see and call this tool? | `Authenticator.authorise()` | spindl, before any tool code runs |
| **Reach** | What may a permitted call touch? Which collections, tenants, accounts, records or hosts? | The credential, as `Identity.reach` | **The tool**, on every read and write it makes |

`authorise()` returning `True` means the tool may run. It says nothing about
what the tool then reads or writes, and it cannot: spindl does not know what
your tool touches. A tool that is allowed to run sees whatever its own code
reaches unless it applies the caller's reach itself. Every tool must apply
`self.context.reach` to every read and every write.

### A worked example

A notes service keeps documents in collections. One analyst's API key
permits the `search_notes` tool, and its reach is two named collections,
`incident-notes` and `threat-intel`, read only. A third collection,
`finance-reports`, exists in the same store.

Reach is opaque to spindl, so it can be any type you like. Here it is a small
frozen dataclass:

```python
from dataclasses import dataclass

NOTES = [
    {"collection": "incident-notes", "id": "N-1", "text": "Phishing wave against example.com staff"},
    {"collection": "threat-intel", "id": "T-7", "text": "Phishing kit served from 203.0.113.10"},
    {"collection": "finance-reports", "id": "F-3", "text": "Quarterly cost of phishing response"},
]


@dataclass(frozen=True)
class CollectionReach:
    """What a credential's calls may touch."""

    collections: frozenset[str]
    can_write: bool = False
```

The search tool declares the permission it needs, `notes:read`, so that the
authenticator can decide tool access. Then, inside `execute`, it applies the
caller's reach to the query:

```python
from typing import Any

from pydantic import BaseModel

from spindl import BaseTool, StructuredError, ErrorDetail


def refuse(message: str) -> dict[str, Any]:
    return StructuredError(
        error=ErrorDetail(
            error_code="OUT_OF_REACH", error_message=message, retry_eligible=False
        )
    ).to_dict()


class SearchNotes(BaseTool):
    name = "search_notes"
    description = "Search notes for a phrase"
    category = "notes"
    read_only = True
    destructive = False
    permissions = ["notes:read"]

    class InputModel(BaseModel):
        phrase: str

    async def execute(self, **params: Any) -> dict[str, Any]:
        args = self.validate_input(params)
        reach = self.context.reach if self.context else None
        if not isinstance(reach, CollectionReach):
            return refuse("This credential carries no collection reach.")
        hits = [
            note
            for note in NOTES
            if note["collection"] in reach.collections  # reach applied to the read
            and args.phrase.lower() in note["text"].lower()
        ]
        return {"success": True, "data": {"notes": hits}}
```

A write tool needs the same care, and more: it checks both that the target
is in reach and that the reach allows writing. Holding the `notes:write`
permission gets a caller past `authorise()`; it does not make every
collection writable.

```python
class AddNote(BaseTool):
    name = "add_note"
    description = "Add a note to a collection"
    category = "notes"
    read_only = False
    destructive = False
    permissions = ["notes:write"]

    class InputModel(BaseModel):
        collection: str
        text: str

    async def execute(self, **params: Any) -> dict[str, Any]:
        args = self.validate_input(params)
        reach = self.context.reach if self.context else None
        if not isinstance(reach, CollectionReach) or not reach.can_write:
            return refuse("This credential may not write notes.")
        if args.collection not in reach.collections:  # reach applied to the write
            return refuse(f"Collection {args.collection!r} is out of reach.")
        note = {"collection": args.collection, "id": f"N-{len(NOTES) + 1}", "text": args.text}
        NOTES.append(note)
        return {"success": True, "data": note}
```

Now the server. API keys carry both controls: `tool_permissions` for tool
access and `reach` for what the calls may touch. `ScopeAuthoriser` allows a
tool when the caller holds every permission it declares.

```python
from spindl import AuthConfig, MCPServer
from spindl.auth import (
    ApiKeyAuthenticator,
    ApiKeyRecord,
    InMemoryApiKeyStore,
    ScopeAuthoriser,
    generate_api_key,
    hash_api_key,
)

store = InMemoryApiKeyStore()
analyst_key = generate_api_key("notes")  # shown once, to the analyst
store.add(
    ApiKeyRecord(
        key_id="analyst-1",
        key_hash=hash_api_key(analyst_key),  # only the hash is stored
        subject="analyst@example.com",
        tool_permissions=frozenset({"notes:read"}),
        reach=CollectionReach(frozenset({"incident-notes", "threat-intel"})),
    )
)

authenticator = ApiKeyAuthenticator(store, authoriser=ScopeAuthoriser())
server = MCPServer(
    prefix="notes",
    auth=AuthConfig(
        authenticator=authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
        credential_headers=authenticator.credential_headers,
    ),
)
server.register_all([SearchNotes(), AddNote()])
```

What the analyst gets:

- `tools/list` shows `notes_search_notes` but not `notes_add_note`: the key
  lacks `notes:write`, so `authorise()` refuses the tool and spindl hides it.
- Searching for "phishing" returns `N-1` and `T-7`. `F-3` matches the phrase
  but sits in `finance-reports`, outside the key's reach, so the tool never
  returns it. `authorise()` had already said yes; only the reach check in
  the tool kept `F-3` out.

<!-- docs-test
analyst = {"X-API-Key": analyst_key}
async with docs_client(server) as client:
    names = {tool["name"] for tool in await client.list(analyst)}
    status, found = await client.call("notes_search_notes", {"phrase": "phishing"}, analyst)
assert "notes_search_notes" in names and "notes_add_note" not in names
assert status == 200
assert [note["id"] for note in found["data"]["notes"]] == ["N-1", "T-7"]
-->

Leave the reach check out and the same call, by the same permitted caller,
returns `F-3` as well:

```python
class SearchNotesWrongly(SearchNotes):
    """Do not do this: authorise() passed, so the tool trusts the caller."""

    async def execute(self, **params: Any) -> dict[str, Any]:
        args = self.validate_input(params)
        hits = [n for n in NOTES if args.phrase.lower() in n["text"].lower()]
        return {"success": True, "data": {"notes": hits}}
```

<!-- docs-test
leaky = MCPServer(
    prefix="notes",
    auth=AuthConfig(
        authenticator=authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
        credential_headers=authenticator.credential_headers,
    ),
)
leaky.register(SearchNotesWrongly())
async with docs_client(leaky) as client:
    status, found = await client.call("notes_search_notes", {"phrase": "phishing"}, analyst)
assert [note["id"] for note in found["data"]["notes"]] == ["N-1", "T-7", "F-3"]

# A lead may write, but only to incident-notes: the tool refuses the rest.
lead_key = generate_api_key("notes")
store.add(
    ApiKeyRecord(
        key_id="lead-1",
        key_hash=hash_api_key(lead_key),
        subject="lead@example.com",
        tool_permissions=frozenset({"notes:read", "notes:write"}),
        reach=CollectionReach(frozenset({"incident-notes"}), can_write=True),
    )
)
lead = {"X-API-Key": lead_key}
async with docs_client(server) as client:
    _, outside = await client.call(
        "notes_add_note", {"collection": "threat-intel", "text": "x"}, lead
    )
    _, inside = await client.call(
        "notes_add_note", {"collection": "incident-notes", "text": "Contained"}, lead
    )
assert outside["error"]["error_code"] == "OUT_OF_REACH"
assert inside["data"]["collection"] == "incident-notes"
-->

In short:

- `authorise()` decides whether a tool may be called. It never limits what
  the tool touches.
- Every tool applies `identity.reach` (as `self.context.reach`) to every
  read and every write it makes, including lookups by identifier, counts,
  exports and anything it passes to another service.
- Tool permissions and reach can disagree. The tool honours the narrower of
  the two, because only the tool sees the data.
- spools created from a tool's response are confined to the caller's
  subject, so a follow-up `spooler_query` cannot see another caller's spool.
  The spool holds only what the tool returned, so it inherits the tool's
  reach check, not a check of its own.

### Reach fails closed

With an `Authenticator` configured, every tool requires reach by default.
When the caller's identity carries none (`Identity.reach is None`), spindl
refuses the call before any tool code runs, with this structured error:

```json
{
  "success": false,
  "platform": "spindl",
  "error": {
    "error_code": "REACH_REQUIRED",
    "error_message": "Tool 'search_notes' was not run: it requires reach (what a call may touch), and this credential carries none. Tool access was decided separately and does not grant reach.",
    "retry_eligible": false,
    "suggestion": "Use a credential whose authenticator sets Identity.reach, or, for a tool that touches nothing caller-specific, set requires_reach = False on the tool class."
  }
}
```

A tool that touches nothing caller-specific (a clock, a unit converter, a
health check) opts out:

```python
class ServerTime(BaseTool):
    name = "server_time"
    description = "The server's current time in UTC"
    category = "meta"
    read_only = True
    destructive = False
    idempotent = False
    open_world = False
    requires_reach = False  # touches nothing a caller owns

    async def execute(self, **params: Any) -> dict[str, Any]:
        from datetime import datetime, timezone

        return {"success": True, "data": datetime.now(timezone.utc).isoformat()}


server.register(ServerTime())
```

<!-- docs-test
nobody_key = generate_api_key("notes")
store.add(
    ApiKeyRecord(
        key_id="nobody-1",
        key_hash=hash_api_key(nobody_key),
        subject="nobody@example.com",
        tool_permissions=frozenset({"notes:read"}),
        reach=None,
    )
)
nobody = {"X-API-Key": nobody_key}
async with docs_client(server) as client:
    _, refused = await client.call("notes_search_notes", {"phrase": "x"}, nobody)
    _, allowed = await client.call("notes_server_time", {}, nobody)
assert refused["error"]["error_code"] == "REACH_REQUIRED"
assert allowed["success"] is True
-->

spindl's built-in tools (`list_tools`, `describe_tool` and the `spooler_*`
tools) set `requires_reach = False`: the skills tools describe only tools
the caller may use, and spools are already confined to the caller's
subject.

`requires_reach` accepts `None` (the default: required when an
`Authenticator` is configured), `True` and `False`. Servers without
authentication, and servers still on the deprecated 0.4 `token_verifier`
or `tool_visibility` interfaces, do not require reach, exactly as in 0.4.

## The pieces

| Name | Where | What it is |
|------|-------|------------|
| `Authenticator` | `spindl`, `spindl.auth` | The protocol you implement (or take from the reference implementations): `authenticate()` and `authorise()` |
| `Credentials` | `spindl`, `spindl.auth` | What the request carried: `bearer_token` and the configured credential `headers` |
| `Identity` | `spindl`, `spindl.auth` | Who the caller is: `subject`, `client_id`, `tool_permissions`, `reach`, `expires_at` |
| `ToolContext` | `spindl`, `spindl.auth` | What a tool sees as `self.context`: `identity`, `reach`, `instance_prefix` |
| `AuthConfig` | `spindl`, `spindl.auth` | The server's authentication settings |

### Authenticator

```python
from typing import Optional, Protocol

from spindl import BaseTool, Credentials, Identity
from spindl.auth import ToolAction


class AuthenticatorShape(Protocol):  # the shape of spindl.Authenticator
    async def authenticate(self, credentials: Credentials) -> Optional[Identity]: ...

    async def authorise(
        self, identity: Identity, tool: BaseTool, action: ToolAction
    ) -> bool: ...
```

- `authenticate(credentials)` returns the caller's `Identity`, or `None`
  when the credential is not valid; spindl then answers `401`. It must check
  everything a resource server is required to check, including that the
  credential was issued for this server (audience binding): `Credentials`
  carry no resource URL, so the authenticator knows its own. If it raises,
  or returns something other than an `Identity`, spindl answers `401` and
  logs only the exception type, never its text.
- `authorise(identity, tool, action)` decides tool access only. `action` is
  `"list"` or `"call"`. It runs before any tool code, may be called several
  times in one request (once per tool when listing, again when calling, and
  twice for a call in step-up mode), so keep it quick and free of side
  effects. If it raises, the tool is denied.

### Identity

`Identity` is a frozen dataclass:

| Field | Meaning |
|-------|---------|
| `subject` | Who the caller is. Required and non-empty. Spools are confined to it. |
| `client_id` | The client application, when known. |
| `tool_permissions` | The tool permissions the credential grants, a `frozenset[str]`. Checked against `AuthConfig.required_scopes` on every request, and usually by `authorise()` against `BaseTool.permissions`. |
| `reach` | What the credential's calls may touch. Any object; spindl never reads it. `None` means no reach. |
| `expires_at` | Seconds since the epoch. An expired identity is answered `401`. |

### Credentials and credential headers

spindl always reads `Authorization: Bearer <token>` into
`Credentials.bearer_token`. To accept credentials in other headers, such as
an API key in `X-API-Key`, name them in `AuthConfig.credential_headers`;
spindl passes their values in `Credentials.headers`, keyed by lower-cased
name. Only headers that were present appear. `Authorization` itself cannot
be listed. Neither value appears in `repr`, so a `Credentials` that reaches
a log line leaks nothing.

### Reading the caller inside a tool

`self.context` is a read-only `ToolContext` for the call the tool is
serving. One tool instance serves concurrent calls, so the value lives in a
context variable, not on the instance; it is `None` outside a call.

```python
class WhoAmI(BaseTool):
    name = "whoami"
    description = "Who the caller is and what the call may touch"
    category = "meta"
    read_only = True
    destructive = False
    requires_reach = False

    async def execute(self, **params: Any) -> dict[str, Any]:
        context = self.context
        identity = context.identity if context else None
        return {
            "success": True,
            "data": {
                "subject": identity.subject if identity else None,
                "permissions": sorted(identity.tool_permissions) if identity else [],
                "instance_prefix": context.instance_prefix if context else None,
            },
        }


server.register(WhoAmI())
```

<!-- docs-test
async with docs_client(server) as client:
    # With an instance prefix the wire name gains it too.
    _, me = await client.call("lab_notes_whoami", {}, {**analyst, "X-Spindl-Prefix": "lab"})
assert me["data"] == {
    "subject": "analyst@example.com",
    "permissions": ["notes:read"],
    "instance_prefix": "lab",
}, me
-->

`spindl.current_identity()` returns the same `Identity` from anywhere in the
request, for code that is not a tool method.

## Configuring a server

`AuthConfig` takes:

| Field | Default | Meaning |
|-------|---------|---------|
| `authenticator` | none | Your `Authenticator`. Required (unless you are on the deprecated `token_verifier`). |
| `resource_server_url` | required | The canonical URL of this MCP endpoint, published as `resource` in the metadata. |
| `authorization_servers` | required | At least one URL clients obtain credentials from. |
| `required_scopes` | `[]` | Permissions every request must carry, checked against `Identity.tool_permissions`. |
| `scopes_supported` | `required_scopes` | Scopes published in the metadata before the tools' permissions are added. |
| `resource_name` | `None` | A human-readable name for the metadata. |
| `serve_metadata` | `True` | Serve the RFC 9728 document. Set `False` when a gateway serves it. |
| `credential_headers` | `[]` | Extra headers to read credentials from. |
| `denial_mode` | `"hide"` | `"hide"` or `"step_up"`; see below. |

Give `AuthConfig` to `MCPServer(auth=...)`. The same configuration protects
`run_http()`, `run_sse()`, `build_http_app()`, `build_sse_app()`,
`http_endpoint()` and `wsgi_app()`.

## What callers see

### 401: no valid credential

A request with no credential, one the authenticator refuses, or one whose
identity has expired, is answered `401` before it reaches the MCP layer:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
Content-Type: application/json

{"error": "invalid_token", "error_description": "Authentication required"}
```

`resource_metadata` points at the protected-resource metadata document, so
an OAuth client can discover where to obtain a token.

### 403: a required scope is missing

A request whose identity lacks one of `AuthConfig.required_scopes` is
answered `403` with `error="insufficient_scope"` and
`error_description="Required scope: <name>"`.

<!-- docs-test
async with docs_client(server) as client:
    anonymous = await client.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    wrong = await client.post(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"X-API-Key": generate_api_key("notes")},
    )
for resp in (anonymous, wrong):
    assert resp.status_code == 401
    challenge = resp.headers["WWW-Authenticate"]
    assert challenge.startswith('Bearer error="invalid_token"'), challenge
    assert 'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
-->

### Tools the caller may not use: denial modes

When `authorise()` refuses a tool, `AuthConfig.denial_mode` decides what
the caller sees.

**`"hide"` (the default).** The tool is left out of `tools/list`,
`{prefix}_list_tools` and `{prefix}_describe_tool`, and a call to it is
answered exactly as a call to a tool that does not exist (`TOOL_NOT_FOUND`).
Nothing in any response hints that it exists. This is the 0.4 behaviour.

**`"step_up"`.** A tool the caller is refused only because it lacks some of
the tool's declared `permissions` stays listed, and a call to it is answered
`403` with an `insufficient_scope` challenge naming exactly the missing
permissions, so an OAuth client can ask for a token that carries them:

```python
step_up_server = MCPServer(
    prefix="notes",
    auth=AuthConfig(
        authenticator=authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
        credential_headers=authenticator.credential_headers,
        denial_mode="step_up",
    ),
)
step_up_server.register_all([SearchNotes(), AddNote()])
```

```http
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_scope", error_description="The tool needs permissions this credential does not hold", scope="notes:write", resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
```

<!-- docs-test
async with docs_client(step_up_server) as client:
    names = {tool["name"] for tool in await client.list(analyst)}
    status, body = await client.call(
        "notes_add_note", {"collection": "incident-notes", "text": "x"}, analyst
    )
assert "notes_add_note" in names
assert status == 403 and body["scope"] == "notes:write"
-->

Any other refusal is still answered as an unknown tool. Over a transport
without an HTTP layer the same call gets an `INSUFFICIENT_SCOPE` structured
error instead of the `403`.

### Permissions and scopes_supported

`BaseTool.permissions` names the permissions a tool needs. Each must be a
valid OAuth scope token (RFC 6749 section 3.3: printable ASCII without
spaces, `"` or `\`); registration raises `ValueError` otherwise. spindl
publishes the union of every registered tool's permissions, together with
`scopes_supported` from the configuration, as `scopes_supported` in the
metadata document, so clients can discover what to ask for:

<!-- docs-test
async with docs_client(server) as client:
    metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
assert metadata.status_code == 200
assert metadata.json()["scopes_supported"] == ["notes:read", "notes:write"]
assert metadata.json()["resource"] == "https://mcp.example.com/mcp"
-->

```json
{
  "resource": "https://mcp.example.com/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read", "notes:write"]
}
```

spindl itself does not compare `permissions` with `tool_permissions`: your
`authorise()` decides, and `ScopeAuthoriser` does exactly that comparison.
Declaring `permissions` without an authoriser that reads them publishes them
but grants nothing and refuses nothing.

## Reference implementations

All of these are in `spindl.auth`. They are optional: any object with the
two methods works.

### ApiKeyAuthenticator

`ApiKeyAuthenticator(store, header="x-api-key", accept_bearer=False,
authoriser=None)` reads an API key from a header (or, with
`accept_bearer=True`, from `Authorization: Bearer` when the header is
absent), hashes it with SHA-256, looks the hash up in an `ApiKeyStore`,
compares hashes in constant time, and refuses revoked and expired keys. The
plaintext key is never stored, logged or shown.

- `generate_api_key(prefix)` returns `<prefix>_<43 random characters>`, 256
  bits from `secrets`. Show it to its holder once and store only
  `hash_api_key(key)`. Keys must be random: a fast hash suits high-entropy
  keys and is wrong for human-chosen passwords, so never accept a password
  as an API key.
- `ApiKeyRecord(key_id, key_hash, subject, tool_permissions, reach,
  expires_at, revoked)` is what a store returns. `key_id` becomes
  `Identity.client_id`.
- `ApiKeyStore` is a protocol with one method, `async lookup(key_hash)`.
  `InMemoryApiKeyStore` implements it for tests and small deployments, with
  `add()` and `revoke(key_id)`; use your database for anything else.
- Pass `credential_headers=authenticator.credential_headers` to
  `AuthConfig`, as in the worked example, so spindl reads the header.
- Without an `authoriser`, every authenticated key may use every tool. Reach
  and `required_scopes` still apply.

### ScopeAuthoriser

`ScopeAuthoriser()` allows a tool when the identity holds every permission
the tool declares; a tool declaring none is allowed for any authenticated
caller. It composes into any authenticator that accepts an `authoriser`,
including both reference authenticators and your own:

```python
class MyAuthenticator:
    def __init__(self) -> None:
        self._scopes = ScopeAuthoriser()

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        return None  # your credential check goes here

    async def authorise(self, identity: Identity, tool: BaseTool, action: ToolAction) -> bool:
        return await self._scopes.authorise(identity, tool, action)
```

<!-- docs-test
from spindl import Authenticator

assert isinstance(MyAuthenticator(), Authenticator)
-->

### JwtAuthenticator

`JwtAuthenticator` verifies JWT access tokens issued by an external OAuth
authorisation server. It is keyword-only:

```python
from spindl.auth import JwtAuthenticator


def reach_from_claims(claims: dict[str, Any]) -> Optional[CollectionReach]:
    collections = claims.get("collections")
    if not isinstance(collections, list):
        return None  # no reach: tools that require it are refused
    return CollectionReach(frozenset(collections), can_write=claims.get("notes_write") is True)


jwt_authenticator = JwtAuthenticator(
    issuer="https://auth.example.com/",
    audience="https://mcp.example.com/mcp",  # must equal resource_server_url
    jwks_url="https://auth.example.com/.well-known/jwks.json",
    claims_to_reach=reach_from_claims,
    authoriser=ScopeAuthoriser(),
)
jwt_server = MCPServer(
    prefix="notes",
    auth=AuthConfig(
        authenticator=jwt_authenticator,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
    ),
)
```

<!-- docs-test
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# A signing key made for this check and thrown away afterwards.
signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
public_jwk.update(kid="docs-key", alg="RS256", use="sig")
checked = JwtAuthenticator(
    issuer="https://auth.example.com/",
    audience="https://mcp.example.com/mcp",
    jwks={"keys": [public_jwk]},
    claims_to_reach=reach_from_claims,
    authoriser=ScopeAuthoriser(),
)


def mint(**claims: Any) -> str:
    now = int(time.time())
    body = {
        "iss": "https://auth.example.com/",
        "aud": "https://mcp.example.com/mcp",
        "sub": "analyst@example.com",
        "iat": now,
        "exp": now + 300,
        "scope": "notes:read",
        **claims,
    }
    return jwt.encode(body, signing_key, algorithm="RS256", headers={"kid": "docs-key"})


identity = await checked.authenticate(Credentials(bearer_token=mint(collections=["threat-intel"])))
assert identity is not None
assert identity.reach == CollectionReach(frozenset({"threat-intel"}))
assert identity.tool_permissions == frozenset({"notes:read"})
assert await checked.authenticate(Credentials(bearer_token=mint(aud="https://other.example.com/mcp"))) is None
no_reach = await checked.authenticate(Credentials(bearer_token=mint()))
assert no_reach is not None and no_reach.reach is None
-->

- **Keys.** Give exactly one of `jwks_url` (HTTPS) and `jwks` (a static JWK
  Set). The key set is fetched in a worker thread, cached for
  `jwks_cache_seconds` (300), refreshed when a token names an unknown key
  id, at most once per `jwks_refresh_interval_seconds` (60), and dropped
  when a refresh fails, so stale keys are never used (fail closed).
- **Algorithms.** Only asymmetric algorithms (`RS256` and `ES256` by
  default; RSA, RSA-PSS, ECDSA and EdDSA variants allowed). `none` and the
  HMAC algorithms are refused at construction.
- **Claims checked.** The signature; `iss` exactly; `aud` equal to
  `audience` (or a list holding it); `exp` and `nbf` with
  `leeway_seconds` (30, at most 120); `sub` required.
- **Audience.** Set `audience` to the same string as
  `AuthConfig.resource_server_url`. That binding is what stops a token
  issued for another service being replayed here.
- **Mapping claims.** `claims_to_reach` is required, so reach is always a
  deliberate choice; it may return `None` (the token then runs only tools
  with `requires_reach = False`). `claims_to_permissions` defaults to the
  `scope` claim (space-separated) or `scp`. If a mapper raises, the token
  is refused.
- **Tool access.** Without an `authoriser`, every authenticated caller may
  use every tool.
- A refused token is answered `401`. The log line gives a fixed reason or
  the exception type, never the token or a claim value.

## Writing your own Authenticator

Any class with the two methods is an `Authenticator`; there is nothing to
inherit. This one accepts session tokens that another part of your system
issued, looked up by their SHA-256 hash:

```python
import hashlib


class SessionTokenAuthenticator:
    """Accepts tokens your own system issued, stored by hash."""

    def __init__(self, sessions: dict[str, Identity]) -> None:
        self._sessions = sessions  # sha256 hex of the token -> Identity

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        token = credentials.bearer_token
        if token is None:
            return None
        return self._sessions.get(hashlib.sha256(token.encode()).hexdigest())

    async def authorise(self, identity: Identity, tool: BaseTool, action: ToolAction) -> bool:
        return set(tool.permissions) <= identity.tool_permissions
```

<!-- docs-test
session_token = generate_api_key("session")
sessions = SessionTokenAuthenticator(
    {
        hashlib.sha256(session_token.encode()).hexdigest(): Identity(
            subject="svc-reporting",
            tool_permissions={"notes:read"},
            reach=CollectionReach(frozenset({"threat-intel"})),
        )
    }
)
assert isinstance(sessions, Authenticator)
own = MCPServer(
    prefix="notes",
    auth=AuthConfig(
        authenticator=sessions,
        resource_server_url="https://mcp.example.com/mcp",
        authorization_servers=["https://auth.example.com/"],
    ),
)
own.register(SearchNotes())
async with docs_client(own) as client:
    _, found = await client.call(
        "notes_search_notes", {"phrase": "phishing"}, {"Authorization": f"Bearer {session_token}"}
    )
assert [note["id"] for note in found["data"]["notes"]] == ["T-7"]
-->

Remember the audience: a credential issued for another service must not be
accepted here. Reference tokens checked by introspection carry their
audience in the introspection response; check it.

## stdio

stdio has no headers and so no credentials. With an `Authenticator`
configured, a server run over stdio has no identity: `authorise()` is not
called, and only tools with `requires_reach = False` run (the built-in tools,
for example). Everything else is refused with `REACH_REQUIRED`. A server
that must serve its full tool set over stdio, to one local user, is
configured without `auth`.

## Deprecated 0.4 interfaces

`AuthConfig(token_verifier=...)` and `MCPServer(tool_visibility=...)` still
work, through adapters that keep 0.4 behaviour exactly (no reach
requirement), and each logs one deprecation warning. Neither can be combined
with an `authenticator`. [Upgrading from 0.4](upgrading-0.5.md) shows how to
move to an `Authenticator`.

## Related pages

- [Annotations](annotations.md): what the tool hints in these examples mean.
- [Transports](transports.md): where authentication applies on each transport.
- [Response Spooler](spooler.md#scope): how spools are confined to a caller.
