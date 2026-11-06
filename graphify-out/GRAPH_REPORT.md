# Graph Report - spindl  (2026-11-05)

## Corpus Check
- 68 files · ~42,764 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 3, .example 1, .in 1)

## Summary
- 1334 nodes · 2916 edges · 89 communities (58 shown, 31 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 513 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6a6f5a4e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SpoolerDistinctTool
- test_visibility.py
- Spool Query Engine
- Protocol Tests
- Tool Input Validation
- Spool Storage Backend
- Spooler Lifecycle
- StructuredError
- Registry and Error Modules
- CI Workflow
- Publish Workflow
- ._cleanup
- Any
- Response Envelopes and Sample Tools
- .prefixed_name
- MCPServer
- Backend Initialisation
- Registry Lookup
- Sample Server
- ASGI Endpoint and SSE
- ToolRegistry
- HTTP App Builder
- Bug Report Template
- Feature Request Template
- Spooler Configuration
- Placeholder Resolution
- test_wsgi.py
- current_identity
- Prefix Stripping
- make_server
- BaseTool Tests
- Issue Template Config
- BaseTool
- Tests
- .wsgi_app
- Prefix System
- make_flask_app
- Version Script
- Lock Script
- Building Tools
- SpoolerAggregateTool
- Package Metadata
- SpoolerQueryTool
- WsgiBridge
- Changelog
- Response Spooler
- .process_response
- SpoolerListSpoolsTool
- Spindl
- auth.py
- .register
- ._handle
- rpc
- WSGI (Flask, Django and other WSGI servers)
- .validate_input
- Skills Guide
- .__call__
- AuthConfig
- wsgi.py
- Transports
- test_backend.py
- SlowTool
- Lifecycle
- ListToolsTool
- DescribeToolTool
- bridge_for
- TestMCPServerArgumentValidation
- subprocess_env
- .__init__
- Building Tools
- Spindl Sample Server
- Query Tools
- PULL_REQUEST_TEMPLATE.md
- TestSpoolerToolMetadata
- API Reference
- Response Spooler
- Transports
- Prefix System
- TokenVerifier
- InMemoryBackend
- TestDeclarations

## God Nodes (most connected - your core abstractions)
1. `MCPServer` - 94 edges
2. `BaseTool` - 72 edges
3. `ResponseSpooler` - 70 edges
4. `SpoolerConfig` - 51 edges
5. `QueryEngine` - 50 edges
6. `SQLiteSpoolBackend` - 36 edges
7. `ToolRegistry` - 35 edges
8. `PrefixResolver` - 31 edges
9. `ToolInputError` - 28 edges
10. `SpoolerDistinctTool` - 27 edges

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

## Communities (89 total, 31 thin omitted)

### Community 0 - "SpoolerDistinctTool"
Cohesion: 0.21
Nodes (4): SpoolerDistinctTool, InputModel, TestSpoolerDistinct, TestSpoolerDistinctFilters

### Community 1 - "test_visibility.py"
Cohesion: 0.12
Nodes (13): call(), EchoTool, make_server(), only_client_a_sees_approve(), session_for(), TestDefaults, TestDiscoveryPair, TestMetadataStrings (+5 more)

### Community 2 - "Spool Query Engine"
Cohesion: 0.08
Nodes (6): QueryEngine, TestDistinctFilters, TestQueryEngineAggregate, TestQueryEngineDistinct, TestQueryEngineList, TestQueryEngineQuery

### Community 3 - "Protocol Tests"
Cohesion: 0.07
Nodes (18): TestBuiltIns, ApproveTool, EchoTool, InputModel, hide_approve(), http_client_for(), http_mcp_client(), in_memory_client() (+10 more)

### Community 4 - "Tool Input Validation"
Cohesion: 0.08
Nodes (12): prefix_resolver(), registry(), sample_tool(), spooler_config(), spooler_with_data(), GetDevices, InputModel, LenientTool (+4 more)

### Community 5 - "Spool Storage Backend"
Cohesion: 0.10
Nodes (5): [0.3.0] - 2026-08-30, Added, Changed, _not_found(), SQLiteSpoolBackend

### Community 7 - "Spooler Lifecycle"
Cohesion: 0.15
Nodes (8): ResponseSpooler, spooler(), spool(), TestDelete, TestEnvelopeUnchanged, TestExpiry, TestScope, TestSyncConveniences

### Community 10 - "CI Workflow"
Cohesion: 0.09
Nodes (26): jobs, lint, test, runs-on, steps, os, python-version, name (+18 more)

### Community 11 - "Publish Workflow"
Cohesion: 0.09
Nodes (26): runs-on, steps, jobs, build, publish, test, name, on (+18 more)

### Community 12 - "._cleanup"
Cohesion: 0.20
Nodes (5): 3. Setup (async, called once before transport starts), Authentication (HTTP and SSE), Building the ASGI app yourself, Reading the caller's identity in a tool, Design Principles

### Community 14 - "Response Envelopes and Sample Tools"
Cohesion: 0.13
Nodes (3): ResponseEnvelope, ResponseMetadata, TestResponseEnvelope

### Community 15 - ".prefixed_name"
Cohesion: 0.16
Nodes (4): _replace(), TestPrefixResolver, run(), set_and_read()

### Community 16 - "MCPServer"
Cohesion: 0.18
Nodes (3): MCPServer, TestMCPServerSetup, TestMCPServerToolCalls

### Community 19 - "Sample Server"
Cohesion: 0.08
Nodes (13): CHANGELOG, Checks, Dependency locks, Integration procedure, Project configuration, Publishing, What spindl is, build_server() (+5 more)

### Community 20 - "ASGI Endpoint and SSE"
Cohesion: 0.12
Nodes (8): Mounting behind an existing gateway, _AsgiEndpoint, _header(), handle_messages(), handle_sse(), handle_mcp(), build_with_http_app(), build_with_http_endpoint()

### Community 21 - "ToolRegistry"
Cohesion: 0.10
Nodes (5): Added, Core Components, PrefixResolver, ToolRegistry, TestContradiction

### Community 22 - "HTTP App Builder"
Cohesion: 0.17
Nodes (7): make_auth(), running_app(), TestHttpAuth, TestMountableTransports, TestSseAuth, WhoAmITool, InputModel

### Community 23 - "Bug Report Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 24 - "Feature Request Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 25 - "Spooler Configuration"
Cohesion: 0.18
Nodes (3): SpoolerConfig, TestInjectedBackend, TestSpoolerConfig

### Community 27 - "test_wsgi.py"
Cohesion: 0.10
Nodes (8): auth_server(), make_auth(), make_server(), no_bridge_thread_left_behind(), server(), StaticVerifier, wait_for(), WhoAmITool

### Community 28 - "current_identity"
Cohesion: 0.20
Nodes (6): Added, Tool Visibility, What it governs, Writing a hook, current_identity(), TestIdentityAccessor

### Community 30 - "make_server"
Cohesion: 0.15
Nodes (9): make_server(), raw_tools_list(), ReadDevices, TestDefinitions, TestWire, TitledOnly, Undeclared, WipeDevice (+1 more)

### Community 33 - "Issue Template Config"
Cohesion: 0.33
Nodes (5): blank_issues_enabled, contact_links, about, name, url

### Community 34 - "BaseTool"
Cohesion: 0.09
Nodes (7): Key Design Decisions, MCP SDK integration uses the low-level API, @placeholder resolution is lazy, The spooler core has zero external dependencies, Tools are stored by bare name, Undeclared arguments are rejected, not dropped, BaseTool

### Community 35 - "Tests"
Cohesion: 0.11
Nodes (3): Changed, SpoolBackend, Tests

### Community 36 - ".wsgi_app"
Cohesion: 0.17
Nodes (8): bridge_threads(), call_wsgi(), start_response(), plain_host(), app(), rpc_headers(), TestLifecycle, TestPlainWsgi

### Community 37 - "Prefix System"
Cohesion: 0.10
Nodes (19): Concurrency Isolation, Level 1: Server Prefix, Level 2: Instance Prefix, Multiple Servers, One Client, Overview, Per-Request Prefixing (HTTP), @Placeholder Syntax, Precedence (+11 more)

### Community 38 - "make_flask_app"
Cohesion: 0.17
Nodes (5): init_app(), make_flask_app(), TestAuthentication, TestFlaskTestClient, tool_text()

### Community 41 - "Building Tools"
Cohesion: 0.12
Nodes (17): Auto-Detect, Building Tools, Complete Example, Custom Guide, Default Guide, Dependency Injection, Error Response, Explicit Array Paths (+9 more)

### Community 42 - "SpoolerAggregateTool"
Cohesion: 0.23
Nodes (4): SpoolerAggregateTool, InputModel, TestSpoolerAggregate, TestSpoolerToolGuides

### Community 49 - "SpoolerQueryTool"
Cohesion: 0.24
Nodes (3): SpoolerQueryTool, InputModel, TestSpoolerQuery

### Community 51 - "Changelog"
Cohesion: 0.14
Nodes (13): [0.4.0] - 2026-10-27, [0.5.0a1] - 2026-11-05, [0.5.0a2] - 2026-11-05, [0.5.0a3] - 2026-11-05, Added, Changed, Changed, Changed (+5 more)

### Community 52 - "Response Spooler"
Cohesion: 0.14
Nodes (14): Argument Validation, Auto-Detect, Configuration, Data Flattening, Enabling the Spooler, Environment Variables, Explicit Array Paths, How It Works (+6 more)

### Community 53 - ".process_response"
Cohesion: 0.23
Nodes (4): Expiry, Scope, Storage Backends, TestResponseSpooler

### Community 54 - "SpoolerListSpoolsTool"
Cohesion: 0.25
Nodes (3): SpoolerListSpoolsTool, TestSpoolerListSpools, TestSpoolerToolsRejectUnknownArguments

### Community 55 - "Spindl"
Cohesion: 0.15
Nodes (13): Architecture, Installation, License, `{prefix}_describe_tool`, `{prefix}_list_tools`, Quick Start, Requirements, Response Types (+5 more)

### Community 56 - "auth.py"
Cohesion: 0.21
Nodes (3): metadata_routes(), _metadata_url(), protect()

### Community 58 - "._handle"
Cohesion: 0.20
Nodes (3): _metadata_path(), _metadata_route(), _Response

### Community 59 - "rpc"
Cohesion: 0.42
Nodes (5): post(), rpc(), running_werkzeug(), TestRealServer, worker()

### Community 60 - "WSGI (Flask, Django and other WSGI servers)"
Cohesion: 0.18
Nodes (9): [0.5.0a4] - 2026-11-05, Added, Changed, Any other WSGI application, Authentication, prefixing and visibility, Flask, Limits, The background thread and its lifecycle (+1 more)

### Community 61 - ".validate_input"
Cohesion: 0.20
Nodes (6): Argument Validation, Handling the Error, Input Parameters, Opting Out, Tools Without Parameters, _summarise()

### Community 62 - "Skills Guide"
Cohesion: 0.18
Nodes (10): Auto-Registered Tools, Categories, describe_tool, list_tools, LLM Workflow, Skills Guide, Structure, Tips (+2 more)

### Community 63 - ".__call__"
Cohesion: 0.18
Nodes (4): ClientDisconnected, _plain(), _read_body(), _status_line()

### Community 64 - "AuthConfig"
Cohesion: 0.24
Nodes (3): AuthConfig, StaticVerifier, TestAuthConfig

### Community 66 - "Transports"
Cohesion: 0.20
Nodes (10): Choosing a Transport, Docker Deployment, HTTP Streamable, Instance Prefix Header, Instance Prefix Header, Multi-Transport Entrypoint, Recommendation, SSE (Server-Sent Events) (+2 more)

### Community 67 - "test_backend.py"
Cohesion: 0.20
Nodes (3): sqlite_config(), TestDefaultBackend, TestSpoolIdUniqueness

### Community 68 - "SlowTool"
Cohesion: 0.20
Nodes (4): EchoTool, InputModel, SlowTool, InputModel

### Community 69 - "Lifecycle"
Cohesion: 0.22
Nodes (8): 1. Construction, 2. Tool Registration, 4. Request Handling, 5. Cleanup, Architecture, Component Overview, Lifecycle, Module Dependency Graph

### Community 75 - ".__init__"
Cohesion: 0.33
Nodes (3): [0.2.0] - 2026-08-21, Fixed, Removed

### Community 76 - "Building Tools"
Cohesion: 0.33
Nodes (6): Argument Validation, Building Tools, Minimal Tool, Spooler Opt-In, Tool Attributes Reference, Tool with Parameters

### Community 77 - "Spindl Sample Server"
Cohesion: 0.33
Nodes (5): Running, Spindl Sample Server, Spooler in action, Tools exposed, What it shows

### Community 79 - "Query Tools"
Cohesion: 0.40
Nodes (5): Query Tools, spooler_aggregate, spooler_distinct, spooler_list, spooler_query

### Community 80 - "PULL_REQUEST_TEMPLATE.md"
Cohesion: 0.40
Nodes (4): Changes, Checklist, Summary, Testing

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

## Knowledge Gaps
- **1 isolated node(s):** `cognisn-spindl`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 483 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **31 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MCPServer` connect `MCPServer` to `SpoolerDistinctTool`, `test_visibility.py`, `Protocol Tests`, `Registry and Error Modules`, `._cleanup`, `Sample Server`, `ASGI Endpoint and SSE`, `ToolRegistry`, `HTTP App Builder`, `test_wsgi.py`, `current_identity`, `make_server`, `spindl/server.py`, `BaseTool`, `Tests`, `.wsgi_app`, `make_flask_app`, `SpoolerAggregateTool`, `SpoolerQueryTool`, `.process_response`, `SpoolerListSpoolsTool`, `.register`, `WSGI (Flask, Django and other WSGI servers)`, `wsgi.py`, `ListToolsTool`, `DescribeToolTool`, `TestMCPServerArgumentValidation`, `.__init__`, `API Reference`?**
  _High betweenness centrality (0.220) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `MCPServer` (e.g. with `Storage Backends` and `The background thread and its lifecycle`) actually correct?**
  _`MCPServer` has 42 INFERRED edges - model-reasoned connections that need verification._
- **What connects `cognisn-spindl` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_visibility.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12375533428165007 - nodes in this community are weakly interconnected._
- **Why does `BaseTool` connect `BaseTool` to `SpoolerDistinctTool`, `test_visibility.py`, `Protocol Tests`, `Tool Input Validation`, `Registry and Error Modules`, `MCPServer`, `Registry Lookup`, `Sample Server`, `ASGI Endpoint and SSE`, `ToolRegistry`, `HTTP App Builder`, `test_wsgi.py`, `current_identity`, `make_server`, `BaseTool Tests`, `spindl/server.py`, `Tests`, `Building Tools`, `SpoolerAggregateTool`, `SpoolerQueryTool`, `Changelog`, `SpoolerListSpoolsTool`, `.register`, `.validate_input`, `SlowTool`, `ListToolsTool`, `DescribeToolTool`, `TestMCPServerArgumentValidation`, `.__init__`, `Spindl Sample Server`, `API Reference`, `TestDeclarations`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `BaseTool` (e.g. with `Added` and `Removed`) actually correct?**
  _`BaseTool` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Should `Spool Query Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.07615018508725542 - nodes in this community are weakly interconnected._