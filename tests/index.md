# Tests

Index of the tests in this folder. Keep it current as tests are added, changed, or removed.

| Test | Covers |
| --- | --- |
| `conftest.py` | Shared fixtures: sample tools, registries, servers, and spooler setups |
| `test_prefix.py` | `PrefixResolver`: server and instance prefixes, context-var isolation, `strip_prefix`, `@placeholder` resolution |
| `test_registry.py` | `ToolRegistry`: registration, duplicate and empty-name errors, lookup by wire name, MCP tool definitions, guide placeholder resolution |
| `test_responses.py` | `ResponseEnvelope`, `ResponseMetadata`, `StructuredError`, `ErrorDetail` serialisation |
| `test_server.py` | `MCPServer`: tool registration, auto-registered skills and spooler tools, request handling |
| `test_tool.py` | `BaseTool`: `InputModel` validation, `execute` and `guide` contracts, spooler attributes |
| `test_tool_validation.py` | `BaseTool` strict argument validation: `accepted_arguments`, unknown-argument rejection, `ToolInputError` payloads, the `reject_unknown_arguments` opt-out |
| `test_annotations.py` | Tool annotations: `title` and the declared hints on `tools/list` (and nothing for undeclared ones), the category in `_meta`, the read-only and destructive contradiction refused, the start-up warning, the built-in tools' annotations, `list_tools` metadata |
| `test_protocol.py` | The `mcp` 2.3 baseline: protocol 2026-07-28 negotiation, `server/discover`, per-request `_meta`, `Mcp-Method` and `Mcp-Name` checks, cacheable `tools/list`, `X-Spindl-Prefix` on HTTP and on SSE message posts, the dependency floor |
| `test_visibility.py` | The deprecated `tool_visibility` hook: hidden tools absent from `tools/list` and `list_tools`, calls and `describe_tool` answered exactly as unknown tools, per-request decisions under concurrency, `None` identity without auth, failing closed, spooler tools, no-hook behaviour; exact protected-resource metadata strings |
| `test_auth.py` | `AuthConfig`, `protect`, RFC 9728 metadata routes, `current_identity`, and the mountable HTTP and SSE transports |
| `test_auth_core.py` | The `Authenticator` protocol: credentials and credential headers, `401` and `403`, `required_scopes`, `authorise` for listing and calling, `denial_mode` hide and step-up, permissions and `scopes_supported`, reach failing closed and `requires_reach`, the 0.4 adapters, on every transport |
| `test_context.py` | `BaseTool.context`: the per-call `ToolContext`, read-only and isolated between concurrent calls |
| `test_auth_api_key.py` | `ApiKeyAuthenticator`, `ApiKeyRecord`, `InMemoryApiKeyStore`, `generate_api_key` and `hash_api_key`: refusals, the header and bearer forms, the plaintext key never kept, over streamable HTTP and the WSGI bridge |
| `test_auth_scopes.py` | `ScopeAuthoriser` and the `Authoriser` protocol, composed into other authenticators |
| `test_auth_jwt.py` | `JwtAuthenticator`: construction limits, signature, issuer, audience, expiry and leeway, the JWKS cache and refresh, claim mappers, logging, end to end with a real JWKS socket |
| `test_wsgi.py` | The WSGI bridge and Flask `init_app`: plain PEP 3333 calls, authentication, metadata routing, lifecycle and thread, optional dependencies, a real Werkzeug server |
| `test_docs_examples.py` | Every Python example in `README.md` and `docs/`, run page by page with the hidden checks beside them; every Python block collected; links between pages resolve |
| `test_sample.py` | The sample server started as a process over HTTP streamable and through its Flask application, called with the `mcp` client: annotations, tool access, reach, `401`; demo keys made at run time |
| `test_spooler/test_config.py` | `SpoolerConfig` defaults, validation, and token estimation |
| `test_spooler/test_spooler.py` | `ResponseSpooler`: initialisation, array auto-detection, spooling thresholds, summary guidance, cleanup |
| `test_spooler/test_backend.py` | `SpoolBackend` protocol, `SQLiteSpoolBackend`, injected backends, spool scoping, expiry, deletion, and spool-ID uniqueness |
| `test_spooler/test_query_engine.py` | `QueryEngine`: query, aggregate, distinct, flattening, and SQL building |
| `test_spooler/test_spooler_tools.py` | The four auto-registered spooler tools: `query`, `aggregate`, `distinct`, `list_spools` |
