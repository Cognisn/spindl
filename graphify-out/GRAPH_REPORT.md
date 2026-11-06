# Graph Report - spindl  (2026-11-05)

## Corpus Check
- 81 files · ~61,357 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 3, .example 1, .in 1)

## Summary
- 2008 nodes · 4941 edges · 116 communities (75 shown, 41 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 703 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `17d48112`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SpoolerDistinctTool
- test_visibility.py
- Spool Query Engine
- Protocol Tests
- GetDevices
- Spool Storage Backend
- Spooler Package Imports
- ResponseSpooler
- Registry and Error Modules
- CI Workflow
- Publish Workflow
- ._cleanup
- ResponseSpooler
- Tests
- PrefixResolver
- MCPServer
- Backend Initialisation
- Registry Lookup
- asyncio
- .build_http_app
- ToolRegistry
- HTTP App Builder
- Bug Report Template
- Feature Request Template
- Spooler Configuration
- Placeholder Resolution
- test_wsgi.py
- make_server
- Prefix Stripping
- .definitions
- make_server
- current_identity
- Issue Template Config
- make_jwt
- .get_connection
- .wsgi_app
- Prefix System
- make_flask_app
- Version Script
- Lock Script
- BaseTool
- Identity
- Package Metadata
- ._step_up_gate
- wsgi.py
- Changelog
- Response Spooler
- .process_response
- ScopeAuthoriser
- Spindl
- .register
- ApiKeyAuthenticator
- tool_text
- make_server
- .validate_input
- Skills Guide
- generate_api_key
- AuthConfig
- test_auth_api_key.py
- Transports
- Any
- SlowTool
- Lifecycle
- ListToolsTool
- DescribeToolTool
- TestConstruction
- ApiKeyRecord
- test_auth_core.py
- .__init__
- Building Tools
- fetching_jwt
- building-tools.md
- Query Tools
- PULL_REQUEST_TEMPLATE.md
- spindl/server.py
- rpc
- Response Spooler
- Transports
- Prefix System
- make_auth
- SpoolerAggregateTool
- SpoolerQueryTool
- TestContradiction
- call_wsgi
- StaticVerifier
- [0.4.0] - 2026-10-27
- call_raw
- SpoolerListSpoolsTool
- .test_context_var_isolation
- JwtAuthenticator
- AccessTokenIdentity
- TestAuthConfig
- test_auth_jwt.py
- jwt.py
- test_backend.py
- jwt_server
- TestBaseTool
- .__init__
- .authorise
- Spindl Sample Server
- TestSpoolerToolMetadata
- .test_no_token_or_claim_value_is_logged
- TestDependencyFloor
- InMemoryBackend
- [0.5.0a7] - 2026-11-05

## God Nodes (most connected - your core abstractions)
1. `MCPServer` - 138 edges
2. `BaseTool` - 121 edges
3. `ResponseSpooler` - 68 edges
4. `make_jwt()` - 63 edges
5. `authenticate()` - 58 edges
6. `make_token()` - 54 edges
7. `Identity` - 52 edges
8. `SpoolerConfig` - 51 edges
9. `QueryEngine` - 50 edges
10. `ApiKeyAuthenticator` - 49 edges

## Surprising Connections (you probably didn't know these)
- `Added` --references--> `JwtAuthenticator`  [INFERRED]
  CHANGELOG.md → src/spindl/auth/jwt.py
- `Added` --references--> `BaseTool`  [INFERRED]
  CHANGELOG.md → src/spindl/tool.py
- `2. Tool Registration` --references--> `PrefixResolver`  [INFERRED]
  docs/architecture.md → src/spindl/prefix.py
- `What it governs` --references--> `ToolRegistry`  [INFERRED]
  docs/visibility.md → src/spindl/registry.py
- `Enabling the Spooler` --references--> `SpoolerConfig`  [INFERRED]
  docs/spooler.md → src/spindl/spooler/config.py

## Import Cycles
- None detected.

## Communities (116 total, 41 thin omitted)

### Community 0 - "SpoolerDistinctTool"
Cohesion: 0.21
Nodes (4): SpoolerDistinctTool, InputModel, TestSpoolerDistinct, TestSpoolerDistinctFilters

### Community 1 - "test_visibility.py"
Cohesion: 0.13
Nodes (13): call(), EchoTool, make_server(), only_client_a_sees_approve(), session_for(), TestDefaults, TestDiscoveryPair, TestMetadataStrings (+5 more)

### Community 2 - "Spool Query Engine"
Cohesion: 0.08
Nodes (6): QueryEngine, TestDistinctFilters, TestQueryEngineAggregate, TestQueryEngineDistinct, TestQueryEngineList, TestQueryEngineQuery

### Community 3 - "Protocol Tests"
Cohesion: 0.07
Nodes (22): is_scope_token(), make_server(), raw_tools_list(), TestBuiltIns, TestWire, wire_tool(), TestTypes, ApproveTool (+14 more)

### Community 4 - "GetDevices"
Cohesion: 0.08
Nodes (12): prefix_resolver(), registry(), sample_tool(), spooler_config(), spooler_with_data(), GetDevices, InputModel, LenientTool (+4 more)

### Community 5 - "Spool Storage Backend"
Cohesion: 0.09
Nodes (5): [0.3.0] - 2026-08-30, Added, Changed, _not_found(), SQLiteSpoolBackend

### Community 7 - "ResponseSpooler"
Cohesion: 0.15
Nodes (8): ResponseSpooler, spooler(), spool(), TestDelete, TestEnvelopeUnchanged, TestExpiry, TestScope, TestSyncConveniences

### Community 9 - "Registry and Error Modules"
Cohesion: 0.13
Nodes (4): ErrorDetail, StructuredError, ToolInputError, TestStructuredError

### Community 10 - "CI Workflow"
Cohesion: 0.09
Nodes (26): jobs, lint, test, runs-on, steps, os, python-version, name (+18 more)

### Community 11 - "Publish Workflow"
Cohesion: 0.09
Nodes (26): runs-on, steps, jobs, build, publish, test, name, on (+18 more)

### Community 12 - "._cleanup"
Cohesion: 0.18
Nodes (6): 3. Setup (async, called once before transport starts), Authentication (HTTP and SSE), Building the ASGI app yourself, Reading the caller's identity in a tool, Design Principles, `MCPServer`

### Community 14 - "Tests"
Cohesion: 0.13
Nodes (4): ResponseEnvelope, ResponseMetadata, Tests, TestResponseEnvelope

### Community 15 - "PrefixResolver"
Cohesion: 0.10
Nodes (5): API Reference, `BaseTool`, `PrefixResolver`, PrefixResolver, TestPrefixResolver

### Community 16 - "MCPServer"
Cohesion: 0.12
Nodes (3): TestMCPServerArgumentValidation, TestMCPServerSetup, TestMCPServerToolCalls

### Community 19 - "asyncio"
Cohesion: 0.07
Nodes (13): CHANGELOG, Checks, Dependency locks, Integration procedure, Project configuration, Publishing, What spindl is, build_server() (+5 more)

### Community 20 - ".build_http_app"
Cohesion: 0.11
Nodes (7): Added, Mounting behind an existing gateway, The background thread and its lifecycle, _AsgiEndpoint, build_with_http_endpoint(), build_with_http_endpoint(), running_sse_server()

### Community 22 - "HTTP App Builder"
Cohesion: 0.15
Nodes (10): MCPServer, build_with_http_app(), make_auth(), running_app(), TestHttpAuth, TestMountableTransports, TestSseAuth, WhoAmITool (+2 more)

### Community 23 - "Bug Report Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 24 - "Feature Request Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 27 - "test_wsgi.py"
Cohesion: 0.10
Nodes (5): no_bridge_thread_left_behind(), subprocess_env(), TestOptionalDependencies, wait_for(), WhoAmITool

### Community 28 - "make_server"
Cohesion: 0.21
Nodes (6): call_tool(), client_for(), make_server(), TestMetadata, TestReach, TestToolAccessHide

### Community 30 - ".definitions"
Cohesion: 0.22
Nodes (5): ReadDevices, TestDefinitions, TitledOnly, Undeclared, WipeDevice

### Community 31 - "make_server"
Cohesion: 0.20
Nodes (6): AssignTool, make_server(), OverlapTool, run_with(), TestToolContext, scenario()

### Community 32 - "current_identity"
Cohesion: 0.15
Nodes (7): identity_from_access_token(), current_identity(), current_tool_context(), _from_sdk_context(), reset_tool_context(), set_tool_context(), ToolContext

### Community 33 - "Issue Template Config"
Cohesion: 0.33
Nodes (5): blank_issues_enabled, contact_links, about, name, url

### Community 34 - "make_jwt"
Cohesion: 0.14
Nodes (6): authenticate(), claims(), make_jwt(), make_token(), TestAccepting, TestRefusing

### Community 36 - ".wsgi_app"
Cohesion: 0.20
Nodes (7): Any other WSGI application, Authentication, prefixing and visibility, Flask, Limits, WSGI (Flask, Django and other WSGI servers), bridge_threads(), TestLifecycle

### Community 37 - "Prefix System"
Cohesion: 0.10
Nodes (19): Concurrency Isolation, Level 1: Server Prefix, Level 2: Instance Prefix, Multiple Servers, One Client, Overview, Per-Request Prefixing (HTTP), @Placeholder Syntax, Precedence (+11 more)

### Community 38 - "make_flask_app"
Cohesion: 0.15
Nodes (5): init_app(), make_auth(), make_flask_app(), TestAuthentication, TestFlaskTestClient

### Community 41 - "BaseTool"
Cohesion: 0.05
Nodes (23): Undeclared arguments are rejected, not dropped, Auto-Detect, Building Tools, Complete Example, Custom Guide, Default Guide, Dependency Injection, Error Response (+15 more)

### Community 42 - "Identity"
Cohesion: 0.05
Nodes (21): Added, TokenVerifierAuthenticator, ToolVisibilityAuthoriser, AuthConfig, reset_identity(), set_identity(), challenge(), metadata_routes() (+13 more)

### Community 49 - "._step_up_gate"
Cohesion: 0.12
Nodes (5): _called_tool_name(), _header(), handle_messages(), handle_sse(), handle_mcp()

### Community 50 - "wsgi.py"
Cohesion: 0.06
Nodes (13): replay(), bridge_for(), _cancel_remaining(), ClientDisconnected, _close_open_bridges(), _metadata_path(), _plain(), _read_body() (+5 more)

### Community 51 - "Changelog"
Cohesion: 0.15
Nodes (12): [0.5.0a1] - 2026-11-05, [0.5.0a2] - 2026-11-05, [0.5.0a3] - 2026-11-05, [0.5.0a6] - 2026-11-05, Added, Changed, Changed, Changed (+4 more)

### Community 52 - "Response Spooler"
Cohesion: 0.14
Nodes (14): Argument Validation, Auto-Detect, Configuration, Data Flattening, Enabling the Spooler, Environment Variables, Explicit Array Paths, How It Works (+6 more)

### Community 53 - ".process_response"
Cohesion: 0.23
Nodes (4): Expiry, Scope, Storage Backends, TestResponseSpooler

### Community 54 - "ScopeAuthoriser"
Cohesion: 0.12
Nodes (11): ScopeAuthoriser, bearer(), identity(), PingTool, product_client(), ProductAuthenticator, ReadTool, ReviseTool (+3 more)

### Community 55 - "Spindl"
Cohesion: 0.15
Nodes (13): Architecture, Installation, License, `{prefix}_describe_tool`, `{prefix}_list_tools`, Quick Start, Requirements, Response Types (+5 more)

### Community 57 - ".register"
Cohesion: 0.15
Nodes (7): TestStartupWarning, auth_server(), authenticator_server(), make_authenticator_server(), make_server(), server(), step_up_server()

### Community 58 - "ApiKeyAuthenticator"
Cohesion: 0.16
Nodes (7): ApiKeyAuthenticator, InMemoryApiKeyStore, header_credentials(), issue(), TestAuthenticate, TestHeaderAndBearer, TestPlaintextIsNeverKept

### Community 59 - "tool_text"
Cohesion: 0.29
Nodes (4): guarded_call(), GuardedWriteTool, TestAuthenticatorThroughTheBridge, tool_text()

### Community 60 - "make_server"
Cohesion: 0.10
Nodes (11): http_client(), make_server(), PingTool, ReadTool, InputModel, RecordingAuthoriser, rpc(), TestAuthorise (+3 more)

### Community 61 - ".validate_input"
Cohesion: 0.20
Nodes (6): Argument Validation, Handling the Error, Input Parameters, Opting Out, Tools Without Parameters, _summarise()

### Community 62 - "Skills Guide"
Cohesion: 0.18
Nodes (10): Auto-Registered Tools, Categories, describe_tool, list_tools, LLM Workflow, Skills Guide, Structure, Tips (+2 more)

### Community 63 - "generate_api_key"
Cohesion: 0.13
Nodes (5): generate_api_key(), hash_api_key(), TestInMemoryStore, TestKeyHelpers, TestRecord

### Community 65 - "test_auth_api_key.py"
Cohesion: 0.15
Nodes (10): Fixture, flask_client(), keys(), TestThroughTheWsgiBridge, wsgi_call(), wsgi_headers(), wsgi_rpc(), wsgi_server() (+2 more)

### Community 66 - "Transports"
Cohesion: 0.20
Nodes (10): Choosing a Transport, Docker Deployment, HTTP Streamable, Instance Prefix Header, Instance Prefix Header, Multi-Transport Entrypoint, Recommendation, SSE (Server-Sent Events) (+2 more)

### Community 67 - "Any"
Cohesion: 0.11
Nodes (9): legacy_auth(), LegacyTool, ReadTool, InputModel, SpoolingTool, TestLegacyAdapters, WhoAmITool, WriteTool (+1 more)

### Community 68 - "SlowTool"
Cohesion: 0.20
Nodes (4): EchoTool, InputModel, SlowTool, InputModel

### Community 69 - "Lifecycle"
Cohesion: 0.14
Nodes (13): 1. Construction, 2. Tool Registration, 4. Request Handling, 5. Cleanup, Architecture, Component Overview, Key Design Decisions, Lifecycle (+5 more)

### Community 72 - "TestConstruction"
Cohesion: 0.12
Nodes (3): default_claims_to_permissions(), TestConstruction, TestDefaultPermissions

### Community 73 - "ApiKeyRecord"
Cohesion: 0.12
Nodes (6): Added, ApiKeyRecord, ApiKeyStore, Authoriser, MisbehavingStore, RaisingStore

### Community 74 - "test_auth_core.py"
Cohesion: 0.12
Nodes (6): clear_executions(), PurgeTool, running_sse_server(), TestPermissionsDeclaration, TestSpoolerConfinement, TestSse

### Community 75 - ".__init__"
Cohesion: 0.22
Nodes (3): [0.2.0] - 2026-08-21, Fixed, Removed

### Community 76 - "Building Tools"
Cohesion: 0.33
Nodes (6): Argument Validation, Building Tools, Minimal Tool, Spooler Opt-In, Tool Attributes Reference, Tool with Parameters

### Community 77 - "fetching_jwt"
Cohesion: 0.19
Nodes (3): FakeClock, fetching_jwt(), TestJwks

### Community 78 - "building-tools.md"
Cohesion: 0.29
Nodes (3): Tool Visibility, What it governs, Writing a hook

### Community 79 - "Query Tools"
Cohesion: 0.40
Nodes (5): Query Tools, spooler_aggregate, spooler_distinct, spooler_list, spooler_query

### Community 80 - "PULL_REQUEST_TEMPLATE.md"
Cohesion: 0.40
Nodes (4): Changes, Checklist, Summary, Testing

### Community 82 - "rpc"
Cohesion: 0.27
Nodes (7): post(), rpc(), rpc_headers(), running_werkzeug(), TestPlainWsgi, TestRealServer, worker()

### Community 83 - "Response Spooler"
Cohesion: 0.50
Nodes (4): Configuration, How It Works, Response Spooler, Spooler Query Tools

### Community 84 - "Transports"
Cohesion: 0.50
Nodes (4): HTTP Streamable, SSE (Server-Sent Events), stdio, Transports

### Community 85 - "Prefix System"
Cohesion: 0.50
Nodes (4): Level 1: Server Prefix (Code), Level 2: Instance Prefix (Runtime), Placeholder Resolution, Prefix System

### Community 87 - "make_auth"
Cohesion: 0.23
Nodes (5): key_headers(), KeyAuthenticator, make_auth(), rpc(), TestMechanics

### Community 88 - "SpoolerAggregateTool"
Cohesion: 0.23
Nodes (4): SpoolerAggregateTool, InputModel, TestSpoolerAggregate, TestSpoolerToolGuides

### Community 89 - "SpoolerQueryTool"
Cohesion: 0.24
Nodes (3): SpoolerQueryTool, InputModel, TestSpoolerQuery

### Community 91 - "call_wsgi"
Cohesion: 0.18
Nodes (7): [0.5.0a4] - 2026-11-05, Added, Changed, call_wsgi(), start_response(), plain_host(), app()

### Community 94 - "call_raw"
Cohesion: 0.22
Nodes (5): call_raw(), list_names(), PingTool, ReviseTool, TestStepUp

### Community 95 - "SpoolerListSpoolsTool"
Cohesion: 0.25
Nodes (3): SpoolerListSpoolsTool, TestSpoolerListSpools, TestSpoolerToolsRejectUnknownArguments

### Community 98 - "AccessTokenIdentity"
Cohesion: 0.20
Nodes (4): [0.5.0a5] - 2026-11-05, Changed, Deprecated, AccessTokenIdentity

### Community 101 - "test_auth_jwt.py"
Cohesion: 0.07
Nodes (14): b64(), hand_made_token(), jwk_for(), jwks_listener(), jwks_server(), JwksHandler, JwksServer, JwksState (+6 more)

### Community 105 - "test_backend.py"
Cohesion: 0.18
Nodes (3): sqlite_config(), TestDefaultBackend, TestSpoolIdUniqueness

### Community 106 - "jwt_server"
Cohesion: 0.36
Nodes (4): jwt_server(), mcp_client(), raw_initialise(), TestEndToEnd

### Community 110 - "Spindl Sample Server"
Cohesion: 0.33
Nodes (5): Running, Spindl Sample Server, Spooler in action, Tools exposed, What it shows

### Community 115 - "[0.5.0a7] - 2026-11-05"
Cohesion: 0.67
Nodes (3): [0.5.0a7] - 2026-11-05, Added, Changed

## Knowledge Gaps
- **1 isolated node(s):** `cognisn-spindl`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 634 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **41 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MCPServer` connect `HTTP App Builder` to `SpoolerDistinctTool`, `test_visibility.py`, `Protocol Tests`, `ResponseSpooler`, `Registry and Error Modules`, `._cleanup`, `Tests`, `MCPServer`, `asyncio`, `.build_http_app`, `ToolRegistry`, `make_server`, `make_server`, `current_identity`, `.wsgi_app`, `make_flask_app`, `BaseTool`, `Identity`, `._step_up_gate`, `wsgi.py`, `.process_response`, `ScopeAuthoriser`, `.register`, `make_server`, `test_auth_api_key.py`, `Any`, `ListToolsTool`, `DescribeToolTool`, `test_auth_core.py`, `.__init__`, `building-tools.md`, `spindl/server.py`, `SpoolerAggregateTool`, `SpoolerQueryTool`, `TestContradiction`, `SpoolerListSpoolsTool`, `TestAuthConfig`, `jwt_server`?**
  _High betweenness centrality (0.240) - this node is a cross-community bridge._
- **Are the 59 inferred relationships involving `MCPServer` (e.g. with `Storage Backends` and `The background thread and its lifecycle`) actually correct?**
  _`MCPServer` has 59 INFERRED edges - model-reasoned connections that need verification._
- **What connects `cognisn-spindl` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_visibility.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12762762762762764 - nodes in this community are weakly interconnected._
- **Why does `BaseTool` connect `BaseTool` to `SpoolerDistinctTool`, `test_visibility.py`, `Protocol Tests`, `GetDevices`, `Registry and Error Modules`, `Tests`, `PrefixResolver`, `MCPServer`, `Registry Lookup`, `asyncio`, `.build_http_app`, `ToolRegistry`, `HTTP App Builder`, `test_wsgi.py`, `Prefix Stripping`, `.definitions`, `make_server`, `current_identity`, `._step_up_gate`, `Changelog`, `ScopeAuthoriser`, `typing`, `.register`, `tool_text`, `make_server`, `.validate_input`, `test_auth_api_key.py`, `Any`, `SlowTool`, `ListToolsTool`, `DescribeToolTool`, `test_auth_core.py`, `.__init__`, `spindl/server.py`, `make_auth`, `SpoolerAggregateTool`, `SpoolerQueryTool`, `TestContradiction`, `call_raw`, `SpoolerListSpoolsTool`, `test_auth_jwt.py`, `jwt.py`, `TestBaseTool`, `Spindl Sample Server`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Are the 31 inferred relationships involving `BaseTool` (e.g. with `Added` and `Removed`) actually correct?**
  _`BaseTool` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Should `Spool Query Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.07615018508725542 - nodes in this community are weakly interconnected._