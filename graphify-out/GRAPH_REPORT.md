# Graph Report - spindl  (2026-11-05)

## Corpus Check
- 75 files · ~51,735 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 3, .example 1, .in 1)

## Summary
- 1628 nodes · 3786 edges · 104 communities (60 shown, 44 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 609 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4e87131a`
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
- .initialise
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
- sample/server.py
- .build_http_app
- ToolRegistry
- HTTP App Builder
- Bug Report Template
- Feature Request Template
- Spooler Configuration
- Placeholder Resolution
- test_wsgi.py
- test_auth_core.py
- Prefix Stripping
- .definitions
- BaseTool
- spindl/server.py
- Issue Template Config
- .get_mcp_tool_definitions
- .get_connection
- .wsgi_app
- Prefix System
- make_flask_app
- Version Script
- Lock Script
- Building Tools
- Identity
- Package Metadata
- MCPServer
- WsgiBridge
- Changelog
- Response Spooler
- .process_response
- sample_tool
- Spindl
- _types.py
- .register
- _Response
- tool_text
- init_app
- .validate_input
- Skills Guide
- ._handle
- AuthConfig
- wsgi.py
- Transports
- AuthConfig
- SlowTool
- Lifecycle
- ListToolsTool
- DescribeToolTool
- bridge_for
- .build_sse_app
- subprocess_env
- .__init__
- Building Tools
- .cleanup
- building-tools.md
- Query Tools
- PULL_REQUEST_TEMPLATE.md
- Project configuration
- API Reference
- Response Spooler
- Transports
- Prefix System
- TestInjectedBackend
- GetDevicesTool
- NoInputTool
- TestContradiction
- .close
- StaticVerifier
- [0.4.0] - 2026-10-27
- Writing Guides
- .test_context_var_isolation

## God Nodes (most connected - your core abstractions)
1. `MCPServer` - 125 edges
2. `BaseTool` - 107 edges
3. `ResponseSpooler` - 68 edges
4. `SpoolerConfig` - 51 edges
5. `QueryEngine` - 50 edges
6. `ToolRegistry` - 47 edges
7. `make_server()` - 43 edges
8. `Identity` - 37 edges
9. `make_auth()` - 36 edges
10. `SQLiteSpoolBackend` - 35 edges

## Surprising Connections (you probably didn't know these)
- `What it governs` --references--> `ToolRegistry`  [INFERRED]
  docs/visibility.md → src/spindl/registry.py
- `Added` --references--> `BaseTool`  [INFERRED]
  CHANGELOG.md → src/spindl/tool.py
- `Dependency Injection` --references--> `BaseTool`  [INFERRED]
  docs/building-tools.md → src/spindl/tool.py
- `Tool Structure` --references--> `BaseTool`  [INFERRED]
  docs/building-tools.md → src/spindl/tool.py
- ``BaseTool`` --references--> `BaseTool`  [INFERRED]
  README.md → src/spindl/tool.py

## Import Cycles
- None detected.

## Communities (104 total, 44 thin omitted)

### Community 0 - "SpoolerDistinctTool"
Cohesion: 0.06
Nodes (16): SpoolerAggregateTool, InputModel, SpoolerDistinctTool, InputModel, SpoolerListSpoolsTool, SpoolerQueryTool, InputModel, InMemoryBackend (+8 more)

### Community 1 - "test_visibility.py"
Cohesion: 0.11
Nodes (13): call(), EchoTool, make_server(), only_client_a_sees_approve(), session_for(), TestDefaults, TestDiscoveryPair, TestMetadataStrings (+5 more)

### Community 2 - "Spool Query Engine"
Cohesion: 0.08
Nodes (6): QueryEngine, TestDistinctFilters, TestQueryEngineAggregate, TestQueryEngineDistinct, TestQueryEngineList, TestQueryEngineQuery

### Community 3 - "Protocol Tests"
Cohesion: 0.05
Nodes (25): make_server(), raw_tools_list(), TestBuiltIns, TestWire, Undeclared, WipeDevice, wire_tool(), TestTypes (+17 more)

### Community 4 - "GetDevices"
Cohesion: 0.20
Nodes (5): GetDevices, InputModel, LenientTool, TestFieldValidation, TestUnknownArguments

### Community 5 - "Spool Storage Backend"
Cohesion: 0.08
Nodes (5): Changed, _not_found(), SpoolBackend, SQLiteSpoolBackend, TestDefaultBackend

### Community 7 - ".initialise"
Cohesion: 0.28
Nodes (4): spool(), TestDelete, TestExpiry, TestScope

### Community 9 - "Registry and Error Modules"
Cohesion: 0.11
Nodes (4): ErrorDetail, StructuredError, ToolInputError, TestStructuredError

### Community 10 - "CI Workflow"
Cohesion: 0.09
Nodes (26): jobs, lint, test, runs-on, steps, os, python-version, name (+18 more)

### Community 11 - "Publish Workflow"
Cohesion: 0.09
Nodes (26): runs-on, steps, jobs, build, publish, test, name, on (+18 more)

### Community 12 - "._cleanup"
Cohesion: 0.15
Nodes (8): 3. Setup (async, called once before transport starts), Authentication (HTTP and SSE), Building the ASGI app yourself, Mounting behind an existing gateway, Reading the caller's identity in a tool, Architecture, Core Components, Design Principles

### Community 13 - "ResponseSpooler"
Cohesion: 0.10
Nodes (3): Spooler guidance uses @placeholders, ResponseSpooler, TestSpoolIdUniqueness

### Community 14 - "Tests"
Cohesion: 0.22
Nodes (4): ResponseEnvelope, ResponseMetadata, Tests, TestResponseEnvelope

### Community 16 - "MCPServer"
Cohesion: 0.17
Nodes (3): TestMCPServerArgumentValidation, TestMCPServerSetup, TestMCPServerToolCalls

### Community 19 - "sample/server.py"
Cohesion: 0.22
Nodes (4): build_server(), main(), GetVulnerabilitiesTool, InputModel

### Community 20 - ".build_http_app"
Cohesion: 0.11
Nodes (7): Added, The background thread and its lifecycle, _AsgiEndpoint, build_with_http_app(), build_with_http_endpoint(), build_with_http_app(), build_with_http_endpoint()

### Community 22 - "HTTP App Builder"
Cohesion: 0.14
Nodes (7): make_auth(), running_app(), TestHttpAuth, TestIdentityAccessor, TestMountableTransports, WhoAmITool, InputModel

### Community 23 - "Bug Report Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 24 - "Feature Request Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 25 - "Spooler Configuration"
Cohesion: 0.21
Nodes (3): SpoolerConfig, sqlite_config(), TestSpoolerConfig

### Community 27 - "test_wsgi.py"
Cohesion: 0.11
Nodes (10): auth_server(), authenticator_server(), GuardedWriteTool, make_auth(), make_authenticator_server(), make_server(), no_bridge_thread_left_behind(), server() (+2 more)

### Community 28 - "test_auth_core.py"
Cohesion: 0.05
Nodes (33): call_raw(), call_tool(), clear_executions(), client_for(), key_headers(), KeyAuthenticator, legacy_auth(), LegacyTool (+25 more)

### Community 30 - ".definitions"
Cohesion: 0.23
Nodes (4): ReadDevices, TestDefinitions, TestListToolsMetadata, TitledOnly

### Community 31 - "BaseTool"
Cohesion: 0.05
Nodes (17): Running, Spindl Sample Server, Spooler in action, Tools exposed, What it shows, BaseTool, TestDeclarations, AssignTool (+9 more)

### Community 32 - "spindl/server.py"
Cohesion: 0.10
Nodes (11): [0.5.0a5] - 2026-11-05, Added, Deprecated, identity_from_access_token(), current_identity(), current_tool_context(), _from_sdk_context(), reset_tool_context() (+3 more)

### Community 33 - "Issue Template Config"
Cohesion: 0.33
Nodes (5): blank_issues_enabled, contact_links, about, name, url

### Community 36 - ".wsgi_app"
Cohesion: 0.16
Nodes (7): bridge_threads(), call_wsgi(), start_response(), plain_host(), app(), TestLifecycle, TestPlainWsgi

### Community 37 - "Prefix System"
Cohesion: 0.10
Nodes (19): Concurrency Isolation, Level 1: Server Prefix, Level 2: Instance Prefix, Multiple Servers, One Client, Overview, Per-Request Prefixing (HTTP), @Placeholder Syntax, Precedence (+11 more)

### Community 38 - "make_flask_app"
Cohesion: 0.18
Nodes (10): make_flask_app(), post(), rpc(), rpc_headers(), running_werkzeug(), TestAuthentication, TestFlaskTestClient, TestRealServer (+2 more)

### Community 41 - "Building Tools"
Cohesion: 0.13
Nodes (15): Auto-Detect, Building Tools, Complete Example, Dependency Injection, Error Response, Explicit Array Paths, Input Parameters, Naming Conventions (+7 more)

### Community 42 - "Identity"
Cohesion: 0.07
Nodes (13): Changed, TokenVerifierAuthenticator, ToolVisibilityAuthoriser, reset_identity(), set_identity(), protect(), _Protected, read_credentials() (+5 more)

### Community 51 - "Changelog"
Cohesion: 0.17
Nodes (11): [0.5.0a1] - 2026-11-05, [0.5.0a2] - 2026-11-05, [0.5.0a3] - 2026-11-05, Added, Changed, Changed, Changed, Changelog (+3 more)

### Community 52 - "Response Spooler"
Cohesion: 0.14
Nodes (14): Argument Validation, Auto-Detect, Configuration, Data Flattening, Enabling the Spooler, Environment Variables, Explicit Array Paths, How It Works (+6 more)

### Community 53 - ".process_response"
Cohesion: 0.16
Nodes (5): Expiry, Scope, Storage Backends, TestEnvelopeUnchanged, TestResponseSpooler

### Community 54 - "sample_tool"
Cohesion: 0.15
Nodes (5): prefix_resolver(), registry(), sample_tool(), spooler_config(), spooler_with_data()

### Community 55 - "Spindl"
Cohesion: 0.17
Nodes (12): Installation, License, `{prefix}_describe_tool`, `{prefix}_list_tools`, Quick Start, Requirements, Response Types, Skills Guide (+4 more)

### Community 56 - "_types.py"
Cohesion: 0.12
Nodes (3): is_scope_token(), TokenVerifier, _check_permissions()

### Community 59 - "tool_text"
Cohesion: 0.39
Nodes (3): guarded_call(), TestAuthenticatorThroughTheBridge, tool_text()

### Community 60 - "init_app"
Cohesion: 0.33
Nodes (6): Any other WSGI application, Authentication, prefixing and visibility, Flask, Limits, WSGI (Flask, Django and other WSGI servers), init_app()

### Community 61 - ".validate_input"
Cohesion: 0.13
Nodes (7): [0.3.0] - 2026-08-30, Added, Undeclared arguments are rejected, not dropped, Argument Validation, Handling the Error, Opting Out, _summarise()

### Community 62 - "Skills Guide"
Cohesion: 0.18
Nodes (10): Auto-Registered Tools, Categories, describe_tool, list_tools, LLM Workflow, Skills Guide, Structure, Tips (+2 more)

### Community 63 - "._handle"
Cohesion: 0.19
Nodes (4): replay(), _plain(), _read_body(), receive()

### Community 65 - "wsgi.py"
Cohesion: 0.15
Nodes (4): ClientDisconnected, _close_open_bridges(), _metadata_path(), _status_line()

### Community 66 - "Transports"
Cohesion: 0.20
Nodes (10): Choosing a Transport, Docker Deployment, HTTP Streamable, Instance Prefix Header, Instance Prefix Header, Multi-Transport Entrypoint, Recommendation, SSE (Server-Sent Events) (+2 more)

### Community 67 - "AuthConfig"
Cohesion: 0.24
Nodes (6): AuthConfig, challenge(), metadata_routes(), document(), handle(), metadata_url()

### Community 68 - "SlowTool"
Cohesion: 0.20
Nodes (4): EchoTool, InputModel, SlowTool, InputModel

### Community 69 - "Lifecycle"
Cohesion: 0.15
Nodes (12): 1. Construction, 2. Tool Registration, 4. Request Handling, 5. Cleanup, Architecture, Component Overview, Key Design Decisions, Lifecycle (+4 more)

### Community 73 - ".build_sse_app"
Cohesion: 0.24
Nodes (5): _header(), handle_messages(), handle_sse(), handle_mcp(), TestSseAuth

### Community 75 - ".__init__"
Cohesion: 0.22
Nodes (3): [0.2.0] - 2026-08-21, Fixed, Removed

### Community 76 - "Building Tools"
Cohesion: 0.33
Nodes (6): Argument Validation, Building Tools, Minimal Tool, Spooler Opt-In, Tool Attributes Reference, Tool with Parameters

### Community 78 - "building-tools.md"
Cohesion: 0.29
Nodes (3): Tool Visibility, What it governs, Writing a hook

### Community 79 - "Query Tools"
Cohesion: 0.40
Nodes (5): Query Tools, spooler_aggregate, spooler_distinct, spooler_list, spooler_query

### Community 80 - "PULL_REQUEST_TEMPLATE.md"
Cohesion: 0.40
Nodes (4): Changes, Checklist, Summary, Testing

### Community 81 - "Project configuration"
Cohesion: 0.25
Nodes (7): CHANGELOG, Checks, Dependency locks, Integration procedure, Project configuration, Publishing, What spindl is

### Community 82 - "API Reference"
Cohesion: 0.50
Nodes (4): API Reference, `BaseTool`, `MCPServer`, `PrefixResolver`

### Community 83 - "Response Spooler"
Cohesion: 0.50
Nodes (4): Configuration, How It Works, Response Spooler, Spooler Query Tools

### Community 84 - "Transports"
Cohesion: 0.50
Nodes (4): HTTP Streamable, SSE (Server-Sent Events), stdio, Transports

### Community 85 - "Prefix System"
Cohesion: 0.50
Nodes (4): Level 1: Server Prefix (Code), Level 2: Instance Prefix (Runtime), Placeholder Resolution, Prefix System

### Community 91 - ".close"
Cohesion: 0.40
Nodes (3): [0.5.0a4] - 2026-11-05, Added, Changed

### Community 94 - "Writing Guides"
Cohesion: 0.50
Nodes (4): Custom Guide, Default Guide, @Placeholder Syntax, Writing Guides

## Knowledge Gaps
- **1 isolated node(s):** `cognisn-spindl`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 563 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **44 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MCPServer` connect `MCPServer` to `SpoolerDistinctTool`, `test_visibility.py`, `Protocol Tests`, `Registry and Error Modules`, `._cleanup`, `ResponseSpooler`, `Tests`, `MCPServer`, `sample/server.py`, `.build_http_app`, `ToolRegistry`, `HTTP App Builder`, `test_wsgi.py`, `test_auth_core.py`, `BaseTool`, `spindl/server.py`, `.get_mcp_tool_definitions`, `.wsgi_app`, `make_flask_app`, `Identity`, `.process_response`, `.register`, `wsgi.py`, `ListToolsTool`, `DescribeToolTool`, `.build_sse_app`, `.__init__`, `building-tools.md`, `API Reference`, `TestContradiction`?**
  _High betweenness centrality (0.274) - this node is a cross-community bridge._
- **Are the 58 inferred relationships involving `MCPServer` (e.g. with `Storage Backends` and `The background thread and its lifecycle`) actually correct?**
  _`MCPServer` has 58 INFERRED edges - model-reasoned connections that need verification._
- **What connects `cognisn-spindl` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SpoolerDistinctTool` be split into smaller, more focused modules?**
  _Cohesion score 0.05789473684210526 - nodes in this community are weakly interconnected._
- **Why does `BaseTool` connect `BaseTool` to `SpoolerDistinctTool`, `test_visibility.py`, `Protocol Tests`, `GetDevices`, `Registry and Error Modules`, `._cleanup`, `Tests`, `MCPServer`, `Registry Lookup`, `sample/server.py`, `.build_http_app`, `ToolRegistry`, `HTTP App Builder`, `test_wsgi.py`, `test_auth_core.py`, `.definitions`, `spindl/server.py`, `.get_mcp_tool_definitions`, `Building Tools`, `MCPServer`, `Changelog`, `sample_tool`, `_types.py`, `.register`, `.validate_input`, `SlowTool`, `ListToolsTool`, `DescribeToolTool`, `.__init__`, `API Reference`, `GetDevicesTool`, `NoInputTool`, `TestContradiction`?**
  _High betweenness centrality (0.178) - this node is a cross-community bridge._
- **Are the 31 inferred relationships involving `BaseTool` (e.g. with `Added` and `Removed`) actually correct?**
  _`BaseTool` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_visibility.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10975609756097561 - nodes in this community are weakly interconnected._