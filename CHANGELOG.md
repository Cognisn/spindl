# Changelog

## [Unreleased]

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
