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
| `test_auth.py` | `AuthConfig`, `protect`, RFC 9728 metadata routes, `current_identity`, and the mountable HTTP and SSE transports |
| `test_spooler/test_config.py` | `SpoolerConfig` defaults, validation, and token estimation |
| `test_spooler/test_spooler.py` | `ResponseSpooler`: initialisation, array auto-detection, spooling thresholds, summary guidance, cleanup |
| `test_spooler/test_backend.py` | `SpoolBackend` protocol, `SQLiteSpoolBackend`, injected backends, spool scoping, expiry, deletion, and spool-ID uniqueness |
| `test_spooler/test_query_engine.py` | `QueryEngine`: query, aggregate, distinct, flattening, and SQL building |
| `test_spooler/test_spooler_tools.py` | The four auto-registered spooler tools: `query`, `aggregate`, `distinct`, `list_spools` |
