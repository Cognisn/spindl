# Graph Report - spindl  (2026-11-05)

## Corpus Check
- Corpus is ~35,785 words - fits in a single context window. You may not need a graph.

## Summary
- 920 nodes · 2078 edges · 49 communities (19 shown, 30 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 349 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Spooler Built-in Tools
- HTTP Authentication
- Spool Query Engine
- Protocol Tests
- Tool Input Validation
- Spool Storage Backend
- Spooler Package Imports
- Spooler Lifecycle
- Error Responses and Skills
- Registry and Error Modules
- CI Workflow
- Publish Workflow
- MCP Server Core
- Response Spooling
- Response Envelopes and Sample Tools
- Prefix Resolver
- Server Setup and Dispatch
- Backend Initialisation
- Registry Lookup
- Sample Server
- ASGI Endpoint and SSE
- Registry Metadata
- HTTP App Builder
- Bug Report Template
- Feature Request Template
- Spooler Configuration
- Placeholder Resolution
- Sample Tools and Identity
- Prefix Stripping
- Mountable Transports
- BaseTool Tests
- Issue Template Config
- Prefix Isolation Test
- Protocol App Builders
- Version Script
- Lock Script
- Spooler Test Config
- Package Metadata

## God Nodes (most connected - your core abstractions)
1. `MCPServer` - 79 edges
2. `ResponseSpooler` - 67 edges
3. `BaseTool` - 50 edges
4. `QueryEngine` - 48 edges
5. `SpoolerConfig` - 47 edges
6. `SQLiteSpoolBackend` - 33 edges
7. `StructuredError` - 32 edges
8. `ErrorDetail` - 31 edges
9. `SpoolerDistinctTool` - 29 edges
10. `ToolInputError` - 26 edges

## Surprising Connections (you probably didn't know these)
- `build_server()` --calls--> `SpoolerConfig`  [INFERRED]
  sample/server.py → src/spindl/spooler/config.py
- `make_auth()` --uses--> `AuthConfig`  [INFERRED]
  tests/test_auth.py → src/spindl/auth.py
- `prefix_resolver()` --uses--> `PrefixResolver`  [INFERRED]
  tests/conftest.py → src/spindl/prefix.py
- `registry()` --uses--> `ToolRegistry`  [INFERRED]
  tests/conftest.py → src/spindl/registry.py
- `TestHttpAuth` --uses--> `MCPServer`  [INFERRED]
  tests/test_auth.py → src/spindl/server.py

## Import Cycles
- None detected.

## Communities (49 total, 30 thin omitted)

### Community 0 - "Spooler Built-in Tools"
Cohesion: 0.06
Nodes (16): SpoolerAggregateTool, InputModel, SpoolerDistinctTool, InputModel, SpoolerListSpoolsTool, SpoolerQueryTool, InputModel, InMemoryBackend (+8 more)

### Community 1 - "HTTP Authentication"
Cohesion: 0.05
Nodes (20): AuthConfig, metadata_routes(), _metadata_url(), protect(), TokenVerifier, StaticVerifier, TestAuthConfig, TestIdentityAccessor (+12 more)

### Community 2 - "Spool Query Engine"
Cohesion: 0.08
Nodes (6): QueryEngine, TestDistinctFilters, TestQueryEngineAggregate, TestQueryEngineDistinct, TestQueryEngineList, TestQueryEngineQuery

### Community 3 - "Protocol Tests"
Cohesion: 0.08
Nodes (17): ApproveTool, EchoTool, InputModel, hide_approve(), http_client_for(), http_mcp_client(), in_memory_client(), make_server() (+9 more)

### Community 4 - "Tool Input Validation"
Cohesion: 0.05
Nodes (12): _summarise(), prefix_resolver(), registry(), sample_tool(), spooler_with_data(), GetDevices, InputModel, LenientTool (+4 more)

### Community 5 - "Spool Storage Backend"
Cohesion: 0.09
Nodes (3): _not_found(), SQLiteSpoolBackend, TestDefaultBackend

### Community 7 - "Spooler Lifecycle"
Cohesion: 0.13
Nodes (10): ResponseSpooler, _run_blocking(), spooler(), spool(), TestDelete, TestEnvelopeUnchanged, TestExpiry, TestScope (+2 more)

### Community 8 - "Error Responses and Skills"
Cohesion: 0.10
Nodes (7): ErrorDetail, StructuredError, DescribeToolTool, InputModel, ListToolsTool, ToolInputError, TestStructuredError

### Community 10 - "CI Workflow"
Cohesion: 0.09
Nodes (26): jobs, lint, test, runs-on, steps, os, python-version, name (+18 more)

### Community 11 - "Publish Workflow"
Cohesion: 0.09
Nodes (26): runs-on, steps, jobs, build, publish, test, name, on (+18 more)

### Community 12 - "MCP Server Core"
Cohesion: 0.10
Nodes (3): MCPServer, TestMCPServerSetup, TestPerRequest

### Community 14 - "Response Envelopes and Sample Tools"
Cohesion: 0.13
Nodes (3): ResponseEnvelope, ResponseMetadata, TestResponseEnvelope

### Community 19 - "Sample Server"
Cohesion: 0.15
Nodes (6): build_server(), main(), GetDevicesTool, InputModel, GetVulnerabilitiesTool, InputModel

### Community 20 - "ASGI Endpoint and SSE"
Cohesion: 0.16
Nodes (5): _AsgiEndpoint, _header(), handle_messages(), handle_sse(), handle_mcp()

### Community 22 - "HTTP App Builder"
Cohesion: 0.26
Nodes (4): make_auth(), running_app(), TestHttpAuth, TestSseAuth

### Community 23 - "Bug Report Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 24 - "Feature Request Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 30 - "Mountable Transports"
Cohesion: 0.22
Nodes (3): TestMountableTransports, WhoAmITool, InputModel

### Community 33 - "Issue Template Config"
Cohesion: 0.33
Nodes (5): blank_issues_enabled, contact_links, about, name, url

## Knowledge Gaps
- **1 isolated node(s):** `cognisn-spindl`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 317 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **30 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MCPServer` connect `MCP Server Core` to `Prefix Context`, `HTTP Authentication`, `Tool Definitions`, `Spooler Built-in Tools`, `Protocol Tests`, `Protocol App Builders`, `Spooler Lifecycle`, `Error Responses and Skills`, `Registry and Error Modules`, `Prefix Resolver`, `Server Setup and Dispatch`, `Sample Server`, `ASGI Endpoint and SSE`, `Registry Metadata`, `HTTP App Builder`, `Spooler Configuration`, `Sample Tools and Identity`, `Mountable Transports`?**
  _High betweenness centrality (0.214) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `MCPServer` (e.g. with `AuthConfig` and `PrefixResolver`) actually correct?**
  _`MCPServer` has 33 INFERRED edges - model-reasoned connections that need verification._
- **What connects `cognisn-spindl` to the rest of the system?**
  _1 weakly-connected nodes found - possible missing edges._
- **Should `Spooler Built-in Tools` be split into smaller, more focused modules?**
  _Cohesion score 0.05789473684210526 - nodes in this community are weakly interconnected._
- **Why does `ResponseSpooler` connect `Spooler Lifecycle` to `Prefix Context`, `Spooler Built-in Tools`, `SQLite Connection`, `Backend Cleanup`, `Spool Storage Backend`, `Spooler Package Imports`, `MCP Server Core`, `Response Spooling`, `Server Setup and Dispatch`, `Backend Initialisation`, `Spooler Configuration`, `Array Flattening`?**
  _High betweenness centrality (0.170) - this node is a cross-community bridge._
- **Are the 19 inferred relationships involving `ResponseSpooler` (e.g. with `MCPServer` and `SpoolBackend`) actually correct?**
  _`ResponseSpooler` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Should `HTTP Authentication` be split into smaller, more focused modules?**
  _Cohesion score 0.05220288781932617 - nodes in this community are weakly interconnected._