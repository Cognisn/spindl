# Changelog

## [Unreleased]

## [0.5.0a6] - 2026-11-05

### Added
- `spindl.auth.api_key.ApiKeyAuthenticator`, a reference `Authenticator` for
  API keys. It reads the key from a header (`X-API-Key` by default) or, when
  `accept_bearer=True`, from `Authorization: Bearer`, hashes it with SHA-256,
  looks the digest up in an `ApiKeyStore`, compares digests in constant time
  and refuses expired and revoked keys. The plaintext key is never stored,
  logged or shown. Pass `credential_headers=authenticator.credential_headers`
  to `AuthConfig`
- `ApiKeyRecord`, the `ApiKeyStore` protocol and `InMemoryApiKeyStore`, with
  `generate_api_key(prefix)` (256 random bits from `secrets`) and
  `hash_api_key(key)`. Keys must be random; never use a human-chosen password
  as an API key
- `spindl.auth.scopes.ScopeAuthoriser`, which allows a tool when the caller
  holds every permission the tool declares (a tool declaring none is allowed
  for any authenticated caller), and the `Authoriser` protocol it implements.
  It composes into any authenticator, including
  `ApiKeyAuthenticator(authoriser=ScopeAuthoriser())` and a product's own
- These API key and authoriser names are also exported from `spindl.auth`

## [0.5.0a5] - 2026-11-05

### Added
- `spindl.auth.Authenticator`: one protocol with
  `authenticate(credentials)`, returning an `Identity` (subject, client id,
  tool permissions, reach and expiry), and
  `authorise(identity, tool, action)`, deciding tool access for listing and
  calling. Configure it with `AuthConfig(authenticator=...)`. spindl reads the
  credentials, answers the `401` and `403` challenges, serves the RFC 9728
  metadata and filters tools
- `AuthConfig.credential_headers` names headers (for example `X-API-Key`)
  that spindl reads and passes to the authenticator in `Credentials`, besides
  `Authorization: Bearer`
- `AuthConfig.denial_mode = "step_up"` keeps a tool listed when the caller
  lacks some of its permissions and answers a call with HTTP `403`
  `insufficient_scope` naming the missing permissions. The default, `"hide"`,
  answers a denied tool exactly as an unknown tool, as in 0.4
- `BaseTool.permissions` declares the permissions a tool needs. They are
  advertised, with the configured scopes, as `scopes_supported` in the
  protected-resource metadata. Registering a permission that is not a valid
  OAuth scope token raises `ValueError`
- `BaseTool.context`, a read-only per-call `ToolContext` with the caller's
  identity, reach and instance prefix, isolated between concurrent calls
- Reach, failing closed: with an authenticator configured, a tool runs only
  when the caller's identity carries reach, unless the tool sets
  `requires_reach = False`. Tool access and reach are separate controls:
  being allowed to call a tool never limits what it touches, so tools apply
  `self.context.reach` themselves
- `Credentials`, `Identity`, `Authenticator` and `ToolContext` are exported
  from `spindl`

### Changed
- `spindl.auth` is a package; every name the 0.4 module exported is still
  available
- `current_identity()` returns an `Identity`. With the deprecated
  `token_verifier` it is an `AccessTokenIdentity`, which keeps the 0.4
  `scopes` and `token` attributes
- spindl's built-in tools (`list_tools`, `describe_tool` and the `spooler_*`
  tools) set `requires_reach = False`
- `ToolRegistry` gains asynchronous lookups that apply the authenticator's
  decision; its synchronous lookups raise `RuntimeError` on a server with an
  authenticator or a visibility hook

### Deprecated
- `AuthConfig(token_verifier=...)` and `MCPServer(tool_visibility=...)`. Both
  keep their 0.4 behaviour through adapters and log a deprecation warning;
  neither can be combined with an authenticator

## [0.5.0a4] - 2026-11-05

### Added
- `MCPServer.wsgi_app()` serves the HTTP streamable transport from any WSGI
  (PEP 3333) application. It runs the endpoint and its lifespan on an event
  loop in a background thread owned by spindl, with authentication, instance
  prefixing and tool visibility unchanged. Responses are JSON; Server-Sent
  Events are not offered through WSGI
- `spindl.wsgi.init_app(app, server, path="/mcp")` mounts a server on a Flask
  application, including the RFC 9728 protected-resource metadata path when
  it is served
- `WsgiBridge.close()` stops the bridge's lifespan and joins its thread; it
  also runs when the interpreter exits
- A `wsgi` extra (`pip install cognisn-spindl[wsgi]`) that installs `a2wsgi`

### Changed
- CI's locked test environment includes the `wsgi` extra and Flask for the
  bridge tests

## [0.5.0a3] - 2026-11-05

### Added
- `BaseTool` declares `title`, `read_only`, `destructive`, `idempotent` and
  `open_world`. `tools/list` sends the title and only the declared hints as
  MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`), so hosts such as Claude Desktop can group tools by what
  they do; undeclared hints take the MCP defaults
- A tool's category is sent in its `_meta` under
  `com.cognisn.spindl/category`
- spindl logs one warning at start-up naming every tool that declares neither
  `read_only` nor `destructive`
- `list_tools` returns each tool's title and its `read_only` and
  `destructive` values

### Changed
- spindl's built-in tools (`list_tools`, `describe_tool` and the `spooler_*`
  tools) declare themselves read-only, non-destructive, idempotent and
  closed-world, with titles
- Registering a tool that declares both `read_only = True` and
  `destructive = True` raises `ValueError`

## [0.5.0a2] - 2026-11-05

### Changed
- spindl now requires `mcp>=2.3,<3` and speaks MCP protocol revision
  2026-07-28 on every transport, while still answering clients that use the
  `initialize` handshake
- `starlette` is declared as a direct dependency, at the floor `mcp` 2.3
  requires
- CI tests one hash-locked environment, `requirements/ci.txt`, on the newest
  `mcp` 2.3.x

### Removed
- Support for the `mcp` 1.x SDK, its handler registration path and the `mcp1`
  CI lock

### Fixed
- `X-Spindl-Prefix` now takes effect on the SSE transport, where `mcp` 2.x
  handles each request in the context of its messages POST

## [0.5.0a1] - 2026-11-05

### Changed
- CI now also runs on pushes to workstream branches (`feat/**`, `fix/**`,
  `docs/**`, `refactor/**`, `chore/**`, `test/**`, `perf/**`, `build/**`,
  `ci/**`, `style/**`, `security/**`), so each workstream has a CI result
  before it is merged

## [0.4.0] - 2026-10-27

### Added
- Per-request tool visibility: `MCPServer(tool_visibility=...)` takes a hook
  that receives the verified identity for the request (or `None` when
  authentication is off) and a tool, and returns whether the tool is visible.
  It governs `tools/list`, `tools/call` and the `list_tools` and
  `describe_tool` skills tools from one place in `ToolRegistry`. A hidden tool
  is answered exactly as an unknown tool, with no hint that it exists. A hook
  that raises hides the tool and logs a warning. With no hook, behaviour is
  unchanged. Documented in `docs/visibility.md`
- `ToolRegistry.set_visibility()` and `ToolRegistry.is_visible()`, and the
  `ToolVisibility` type

### Fixed
- The RFC 9728 protected-resource metadata document now carries `resource`
  and `authorization_servers` exactly as configured. Previously each
  authorisation server URL passed through pydantic's `AnyHttpUrl`, which added
  a trailing slash, so `https://auth.example` was served as
  `https://auth.example/` and no longer matched that server's `issuer`

## [0.3.0] - 2026-08-30

### Added
- `spooler_distinct` accepts `filters`, using the same structure and
  operators as `spooler_query` and `spooler_aggregate`, so uniqueness can be
  asked of a subset rather than only of the whole spool. The response echoes
  `filters_applied` (#15)
- `BaseTool.validate_input()` and `BaseTool.accepted_arguments()`, and the
  `ToolInputError` exception, exported from `spindl`

### Changed
- Tools now reject arguments they do not declare instead of discarding them.
  An unknown argument returns a structured `INVALID_ARGUMENTS` error naming
  both the rejected keys and the accepted ones. The check runs at the MCP
  boundary, so a tool is covered whether or not it validates its own
  parameters. A tool that deliberately takes free-form arguments sets
  `reject_unknown_arguments = False` (#16)

  Silent discard is a correctness hazard for a model-facing API rather than
  a wart: the caller believes the constraint was applied and presents
  dataset-wide results as a filtered answer.
- `InputModel` field violations return `INVALID_ARGUMENTS` with the offending
  field named, rather than the previous `INTERNAL_ERROR`
- `SpoolBackend.distinct()` takes a `filters` keyword argument. Backends
  outside this repository must accept it; the spooler tool always passes it
- `SpoolBackend.query()` and `aggregate()` annotate `filters` as
  `list[dict[str, Any]]`, matching what the tools have always passed
- `sample/` reformatted with black and isort, and the CI lint step widened to
  cover it. It had drifted because CI only checked `src/` and `tests/`

## [0.2.0] - 2026-08-21

### Added
- Resource-server authentication for the HTTP and SSE transports via
  `MCPServer(auth=AuthConfig(...))`: bearer-token verification through a
  pluggable `TokenVerifier`, scope enforcement, the RFC 9728 protected-resource
  metadata document, and `401`/`403` challenges. The authorisation server
  itself stays with the adopter (#6)
- `spindl.current_identity()` to read the authenticated caller's `AccessToken`
  from within `BaseTool.execute`
- `MCPServer.build_http_app()` and `build_sse_app()` return the Starlette
  application for embedding or testing
- `MCPServer.http_endpoint()` and `http_lifespan` so the HTTP transport can be
  registered as a route on an existing Starlette or FastAPI gateway at an exact
  path; the endpoint carries its own bearer-token stack when `auth` is set (#9)
- `build_http_app(path=...)` and `build_sse_app(sse_path=..., messages_path=...)`
  to serve at the sub-application root for mounting under a prefix (#9)
- `AuthConfig(serve_metadata=False)` to suppress Spindl's RFC 9728 metadata
  routes when a gateway already serves discovery at the origin (#9)
- Asynchronous `SpoolBackend` protocol with `SQLiteSpoolBackend` as the default;
  inject a shared backend with `SpoolerConfig(backend=...)` for multi-replica
  deployments (#7)
- Spool scoping: spools created during an authenticated request are owned by
  the caller's subject and hidden from other callers (`scope_from_identity`,
  or an explicit `scope=` on `process_response`)
- Spool expiry via `process_response(ttl=...)`,
  `SpoolerConfig(default_ttl_seconds=...)`, or `SPOOLER_DEFAULT_TTL_SECONDS`
- `SpoolBackend.delete_spool()`
- Support for `mcp` 2.x alongside 1.x (`mcp>=1.25,<3`): handler registration
  uses `add_request_handler` on 2.x and the decorator API on 1.x (#8, #10, #11)
- Python 3.10 and 3.11 support; `requires-python` lowered to `>=3.10` and the
  CI matrix now covers 3.10 to 3.13 against both `mcp` series (#10, #11)
- Sample MCP server (`sample/`) demonstrating framework usage with two tools:
  `get_devices` (inventory, `spooler_auto_detect`) and `get_vulnerabilities`
  (security, explicit `spooler_array_paths`), with a README

### Changed
- `SpoolBackend` methods are `async`, and `ResponseSpooler.process_response`
  is now a coroutine so network backends never block the event loop. Callers
  that used `process_response` directly must `await` it; `initialise_async()`
  and `cleanup_async()` are added for use inside an event loop
- The four spooler tools delegate to the configured backend instead of
  constructing a `QueryEngine` on the SQLite connection directly.
  `ResponseSpooler.get_connection()` is retained for the SQLite backend
- Package fully typed under `mypy --strict`; black and isort applied
  throughout, with black's `target-version` pinned
- CI and the publish workflow install from hash-locked requirement files
  (`requirements/ci-mcp1.txt`, `ci-mcp2.txt`, `build.txt`, regenerated with
  `scripts/lock-ci.sh`); `uv.lock` records the resolved development
  environment for `uv sync`
- Unexpected errors in tool handlers are logged with `logging.exception` so the
  traceback is retained
- `httpx` and `pytest-timeout` added to the `dev` extra (`mcp` 2.x no longer
  depends on `httpx`)
- Documentation updated throughout to remove read-only and write-operation
  references

### Removed
- `is_write_operation` attribute from `BaseTool` -- read-only filtering is a
  server-level concern, not a framework responsibility
- `read_only` parameter from `MCPServer.__init__()` and the associated
  registration filtering logic

### Fixed
- The HTTP streamable transport now uses the SDK's
  `StreamableHTTPSessionManager`; the previous implementation called the
  transport with an incompatible signature and could not serve requests
- Spool IDs now include random bytes as well as the timestamp. On platforms
  with coarse clock resolution (Windows, about 15 ms) two spools created in
  quick succession from the same tool and path could share an ID, and the
  second silently replaced the first
