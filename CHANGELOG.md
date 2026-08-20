# Changelog

## [Unreleased]

## [0.2.0a1] - 2026-08-20

### Added
- Resource-server authentication for the HTTP and SSE transports via
  `MCPServer(auth=AuthConfig(...))`: bearer-token verification through a
  pluggable `TokenVerifier`, scope enforcement, the RFC 9728 protected-resource
  metadata document, and `401`/`403` challenges (#6)
- `spindl.current_identity()` to read the authenticated caller's `AccessToken`
  from within `BaseTool.execute`
- `MCPServer.build_http_app()` and `build_sse_app()` return the Starlette
  application for embedding or testing
- `SpoolBackend` protocol with `SQLiteSpoolBackend` as the default; inject a
  shared backend with `SpoolerConfig(backend=...)` for multi-replica
  deployments (#7)
- Spool scoping: spools created during an authenticated request are owned by
  the caller's subject and hidden from other callers (`scope_from_identity`,
  or an explicit `scope=` on `process_response`)
- Spool expiry via `process_response(ttl=...)`, `SpoolerConfig(default_ttl_seconds=...)`,
  or `SPOOLER_DEFAULT_TTL_SECONDS`
- `SpoolBackend.delete_spool()`

### Changed
- The four spooler tools delegate to the configured backend instead of
  constructing a `QueryEngine` on the SQLite connection directly.
  `ResponseSpooler.get_connection()` is retained for the SQLite backend.

### Fixed
- The HTTP streamable transport now uses the SDK's `StreamableHTTPSessionManager`;
  the previous implementation called the transport with an incompatible
  signature and could not serve requests

### Fixed
- Pinned `mcp<2.0.0`: the 2.0 SDK removed the low-level `Server.list_tools` and
  `call_tool` decorators that `MCPServer` relies on, breaking server start-up

### Added
- Sample MCP server (`sample/`) demonstrating framework usage with two tools:
  - `get_devices` -- inventory tool with `spooler_auto_detect`
  - `get_vulnerabilities` -- security tool with explicit `spooler_array_paths`
- Sample README with usage instructions and feature overview

### Removed
- `is_write_operation` attribute from `BaseTool` -- read-only filtering is a
  server-level concern, not a framework responsibility
- `read_only` parameter from `MCPServer.__init__()` and the associated
  registration filtering logic
- `write_tool` test fixture and read-only mode tests

### Changed
- Updated `.gitignore` to exclude `__pycache__/`, `*.pyc`, `*.egg-info/`,
  `.DS_Store`, and `.idea/`
- Removed cached `__pycache__` and `.DS_Store` files from version control
- Updated all documentation to remove read-only / write-operation references:
  - `README.md` -- removed Read-Only Mode section, updated API reference and
    tool attributes table
  - `docs/building-tools.md` -- removed Write Operations section and
    `is_write_operation` from tool structure
  - `docs/architecture.md` -- removed read-only bullet from registration
    lifecycle
