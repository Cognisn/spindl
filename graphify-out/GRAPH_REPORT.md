# Graph Report - spindl  (2026-11-06)

## Corpus Check
- 89 files · ~73,803 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 3, .example 1, .in 1)

## Summary
- 2138 nodes · 5335 edges · 107 communities (74 shown, 33 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 823 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a8782a2b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SpoolerDistinctTool
- test_visibility.py
- Spool Query Engine
- in_memory_client
- GetDevices
- Spool Storage Backend
- Spooler Package Imports
- ResponseSpooler
- Registry and Error Modules
- CI Workflow
- Publish Workflow
- .build_sse_app
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
- .definitions
- make_server
- current_identity
- Issue Template Config
- make_jwt
- SpoolBackend
- .wsgi_app
- Prefix System
- make_flask_app
- Version Script
- Lock Script
- Building Tools
- Identity
- Package Metadata
- ._step_up_gate
- wsgi.py
- test_sample.py
- Response Spooler
- .process_response
- ScopeAuthoriser
- Spindl
- auth/__init__.py
- .register
- ApiKeyAuthenticator
- 6. ToolRegistry lookups
- make_server
- BaseTool
- Skills Guide
- generate_api_key
- AuthConfig
- test_auth_api_key.py
- Transports
- make_server
- SlowTool
- Lifecycle
- init_app
- DescribeToolTool
- TestConstruction
- ApiKeyRecord
- MCPServer
- ToolVisibilityAuthoriser
- .test_with_the_scope_authoriser
- fetching_jwt
- authentication.md
- sample_tool
- PULL_REQUEST_TEMPLATE.md
- spindl/server.py
- tool_text
- JwksServer
- EchoTool
- Project configuration
- Tool Annotations
- subprocess_env
- A lead may write, but only to incident-notes: the tool refuses the rest.
- TestContradiction
- call_wsgi
- Use Cases
- test_docs_examples.py
- jwt.py
- AccessTokenIdentity
- test_auth_jwt.py
- jwt_server
- .test_no_token_or_claim_value_is_logged
- TestDependencyFloor
- Authenticator

## God Nodes (most connected - your core abstractions)
1. `MCPServer` - 129 edges
2. `BaseTool` - 116 edges
3. `ResponseSpooler` - 66 edges
4. `make_jwt()` - 63 edges
5. `Identity` - 62 edges
6. `authenticate()` - 58 edges
7. `ApiKeyAuthenticator` - 54 edges
8. `make_token()` - 54 edges
9. `QueryEngine` - 50 edges
10. `SpoolerConfig` - 49 edges

## Surprising Connections (you probably didn't know these)
- `Publishing` --references--> `main()`  [INFERRED]
  CLAUDE.md → sample/server.py
- `Lifecycle` --references--> `MCPServer`  [INFERRED]
  docs/spooler.md → src/spindl/server.py
- `Added` --references--> `JwtAuthenticator`  [INFERRED]
  CHANGELOG.md → src/spindl/auth/jwt.py
- `Added` --references--> `BaseTool`  [INFERRED]
  CHANGELOG.md → src/spindl/tool.py
- `Features` --references--> `Authenticator`  [INFERRED]
  README.md → src/spindl/auth/_types.py

## Import Cycles
- None detected.

## Communities (107 total, 33 thin omitted)

### Community 0 - "SpoolerDistinctTool"
Cohesion: 0.06
Nodes (16): SpoolerAggregateTool, InputModel, SpoolerDistinctTool, InputModel, SpoolerListSpoolsTool, SpoolerQueryTool, InputModel, InMemoryBackend (+8 more)

### Community 1 - "test_visibility.py"
Cohesion: 0.13
Nodes (13): call(), EchoTool, make_server(), only_client_a_sees_approve(), session_for(), TestDefaults, TestDiscoveryPair, TestMetadataStrings (+5 more)

### Community 2 - "Spool Query Engine"
Cohesion: 0.08
Nodes (6): QueryEngine, TestDistinctFilters, TestQueryEngineAggregate, TestQueryEngineDistinct, TestQueryEngineList, TestQueryEngineQuery

### Community 3 - "in_memory_client"
Cohesion: 0.27
Nodes (6): in_memory_client(), payload(), sse_mcp_client(), TestInMemory, TestSse, tool_names()

### Community 4 - "GetDevices"
Cohesion: 0.13
Nodes (7): GetDevices, InputModel, LenientTool, NoInputTool, TestAcceptedArguments, TestFieldValidation, TestUnknownArguments

### Community 5 - "Spool Storage Backend"
Cohesion: 0.06
Nodes (21): [0.3.0] - 2026-08-30, [0.4.0] - 2026-10-27, [0.5.0a1] - 2026-11-05, [0.5.0a2] - 2026-11-05, [0.5.0a3] - 2026-11-05, [0.5.0a6] - 2026-11-05, [0.5.0a7] - 2026-11-05, Added (+13 more)

### Community 7 - "ResponseSpooler"
Cohesion: 0.15
Nodes (7): ResponseSpooler, spool(), TestDelete, TestEnvelopeUnchanged, TestExpiry, TestScope, TestSpoolIdUniqueness

### Community 9 - "Registry and Error Modules"
Cohesion: 0.10
Nodes (4): ErrorDetail, StructuredError, ToolInputError, TestStructuredError

### Community 10 - "CI Workflow"
Cohesion: 0.09
Nodes (26): jobs, lint, test, runs-on, steps, os, python-version, name (+18 more)

### Community 11 - "Publish Workflow"
Cohesion: 0.09
Nodes (26): runs-on, steps, jobs, build, publish, test, name, on (+18 more)

### Community 12 - ".build_sse_app"
Cohesion: 0.11
Nodes (13): Fixed, 3. Setup (async, called once before transport starts), Configuring a server, Building the ASGI app yourself, A session manager runs once; the WSGI example below serves this server again., Licence, Prefix System, Requirements (+5 more)

### Community 14 - "Tests"
Cohesion: 0.12
Nodes (4): ResponseEnvelope, ResponseMetadata, ListToolsTool, TestResponseEnvelope

### Community 15 - "PrefixResolver"
Cohesion: 0.08
Nodes (5): PrefixResolver, TestPrefixResolver, run(), set_and_read(), TestStripPrefix

### Community 16 - "MCPServer"
Cohesion: 0.15
Nodes (3): TestMCPServerArgumentValidation, TestMCPServerSetup, TestMCPServerToolCalls

### Community 19 - "sample/server.py"
Cohesion: 0.07
Nodes (12): announce_keys(), build_server(), main(), AcknowledgeFindingTool, InputModel, GetDevicesTool, InputModel, GetVulnerabilitiesTool (+4 more)

### Community 20 - ".build_http_app"
Cohesion: 0.13
Nodes (6): Mounting behind an existing gateway, _AsgiEndpoint, build_with_http_app(), build_with_http_endpoint(), build_with_http_app(), build_with_http_endpoint()

### Community 22 - "HTTP App Builder"
Cohesion: 0.18
Nodes (6): make_auth(), running_app(), TestHttpAuth, TestMountableTransports, WhoAmITool, InputModel

### Community 23 - "Bug Report Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 24 - "Feature Request Template"
Cohesion: 0.13
Nodes (14): description, label, options, placeholder, value, body, attributes, id (+6 more)

### Community 25 - "Spooler Configuration"
Cohesion: 0.18
Nodes (3): SpoolerConfig, TestSyncConveniences, TestSpoolerConfig

### Community 27 - "test_wsgi.py"
Cohesion: 0.11
Nodes (13): auth_server(), authenticator_server(), GuardedWriteTool, KeyAuthenticator, make_auth(), make_authenticator_server(), make_server(), no_bridge_thread_left_behind() (+5 more)

### Community 28 - "test_auth_core.py"
Cohesion: 0.06
Nodes (31): call_raw(), call_tool(), clear_executions(), client_for(), key_headers(), KeyAuthenticator, legacy_auth(), LegacyTool (+23 more)

### Community 30 - ".definitions"
Cohesion: 0.14
Nodes (10): make_server(), raw_tools_list(), ReadDevices, TestDefinitions, TestListToolsMetadata, TestWire, TitledOnly, Undeclared (+2 more)

### Community 31 - "make_server"
Cohesion: 0.16
Nodes (8): AssignTool, call(), Keys, make_server(), OverlapTool, run_with(), TestToolContext, scenario()

### Community 32 - "current_identity"
Cohesion: 0.11
Nodes (15): [0.5.0a5] - 2026-11-05, Added, Deprecated, Reading the caller inside a tool, Permissions, Reach and the Call's Context, Authentication (HTTP, SSE and WSGI), Reading the caller's identity in a tool, identity_from_access_token() (+7 more)

### Community 33 - "Issue Template Config"
Cohesion: 0.33
Nodes (5): blank_issues_enabled, contact_links, about, name, url

### Community 34 - "make_jwt"
Cohesion: 0.15
Nodes (5): authenticate(), make_jwt(), make_token(), TestAccepting, TestRefusing

### Community 35 - "SpoolBackend"
Cohesion: 0.14
Nodes (3): Changed, SpoolBackend, TestDefaultBackend

### Community 36 - ".wsgi_app"
Cohesion: 0.18
Nodes (6): [0.5.0a4] - 2026-11-05, Added, Changed, The background thread and its lifecycle, bridge_threads(), TestLifecycle

### Community 37 - "Prefix System"
Cohesion: 0.13
Nodes (14): Concurrency Isolation, Level 1: Server Prefix, Level 2: Instance Prefix, Overview, @Placeholder Syntax, Precedence, Prefix System, PrefixResolver API (+6 more)

### Community 38 - "make_flask_app"
Cohesion: 0.16
Nodes (6): guarded_call(), make_flask_app(), rpc_headers(), TestAuthentication, TestAuthenticatorThroughTheBridge, TestFlaskTestClient

### Community 41 - "Building Tools"
Cohesion: 0.11
Nodes (19): Annotations, Attributes Reference, Auto-Detect, Building Tools, Complete Example, Custom Guide, Default Guide, Dependency Injection (+11 more)

### Community 42 - "Identity"
Cohesion: 0.10
Nodes (12): 4. Request Handling, Authenticator, Credentials and credential headers, Identity, The pieces, reset_identity(), set_identity(), _Protected (+4 more)

### Community 49 - "._step_up_gate"
Cohesion: 0.12
Nodes (5): _called_tool_name(), _header(), handle_messages(), handle_sse(), handle_mcp()

### Community 50 - "wsgi.py"
Cohesion: 0.06
Nodes (13): replay(), bridge_for(), _cancel_remaining(), ClientDisconnected, _close_open_bridges(), _metadata_path(), _plain(), _read_body() (+5 more)

### Community 51 - "test_sample.py"
Cohesion: 0.16
Nodes (13): _accepts(), check_the_sample(), child_env(), _drain(), free_port(), mcp_client(), payload(), RunningSample (+5 more)

### Community 52 - "Response Spooler"
Cohesion: 0.11
Nodes (19): Argument Validation, Auto-Detect, Configuration, Data Flattening, Enabling the Spooler, Environment Variables, Explicit Array Paths, How It Works (+11 more)

### Community 53 - ".process_response"
Cohesion: 0.18
Nodes (4): Expiry, Scope, Storage Backends, TestResponseSpooler

### Community 54 - "ScopeAuthoriser"
Cohesion: 0.08
Nodes (24): 401: no valid credential, 403: a required scope is missing, Permissions and scopes_supported, Tools the caller may not use: denial modes, What callers see, API keys, Running, Spindl Sample Server (+16 more)

### Community 55 - "Spindl"
Cohesion: 0.33
Nodes (6): Authentication in Brief, Features, Installation, Quick Start, Spindl, The Problem

### Community 56 - "auth/__init__.py"
Cohesion: 0.09
Nodes (13): 3. The auth package, TokenVerifierAuthenticator, AuthConfig, challenge(), metadata_routes(), document(), handle(), metadata_url() (+5 more)

### Community 58 - "ApiKeyAuthenticator"
Cohesion: 0.17
Nodes (8): 7. What else is new, ApiKeyAuthenticator, InMemoryApiKeyStore, header_credentials(), issue(), TestAuthenticate, TestHeaderAndBearer, TestPlaintextIsNeverKept

### Community 60 - "make_server"
Cohesion: 0.24
Nodes (5): http_client(), make_server(), rpc(), TestThroughStreamableHttp, tool_text()

### Community 61 - "BaseTool"
Cohesion: 0.06
Nodes (11): Added, Argument Validation, Handling the Error, Input Parameters, Opting Out, Tools Without Parameters, _check_permissions(), BaseTool (+3 more)

### Community 62 - "Skills Guide"
Cohesion: 0.12
Nodes (12): Auto-Registered Tools, Categories, describe_tool, list_tools, LLM Workflow, Skills Guide, Structure, Tips (+4 more)

### Community 63 - "generate_api_key"
Cohesion: 0.14
Nodes (5): issue_demo_keys(), generate_api_key(), hash_api_key(), TestKeyHelpers, TestRecord

### Community 65 - "test_auth_api_key.py"
Cohesion: 0.15
Nodes (11): Fixture, flask_client(), keys(), PingTool, TestThroughTheWsgiBridge, wsgi_call(), wsgi_headers(), wsgi_rpc() (+3 more)

### Community 66 - "Transports"
Cohesion: 0.20
Nodes (10): Choosing a Transport, Docker Deployment, HTTP Streamable, Instance Prefix Header, Instance Prefix Header, Multi-Transport Entrypoint, Recommendation, SSE (Server-Sent Events) (+2 more)

### Community 67 - "make_server"
Cohesion: 0.34
Nodes (5): http_client_for(), http_mcp_client(), make_server(), rpc(), TestStreamableHttp

### Community 68 - "SlowTool"
Cohesion: 0.18
Nodes (4): EchoTool, InputModel, SlowTool, InputModel

### Community 69 - "Lifecycle"
Cohesion: 0.14
Nodes (14): 1. Construction, 2. Tool Registration, 5. Cleanup, Architecture, Component Overview, Key Design Decisions, Lifecycle, MCP SDK integration uses the low-level API (+6 more)

### Community 70 - "init_app"
Cohesion: 0.16
Nodes (7): Any other WSGI application, Authentication, prefixing and tool access, Flask, Limits, WSGI (Flask, Django and other WSGI servers), create_app(), init_app()

### Community 72 - "TestConstruction"
Cohesion: 0.12
Nodes (3): default_claims_to_permissions(), TestConstruction, TestDefaultPermissions

### Community 73 - "ApiKeyRecord"
Cohesion: 0.10
Nodes (7): Added, ApiKeyAuthenticator, ApiKeyRecord, ApiKeyStore, MisbehavingStore, RaisingStore, TestInMemoryStore

### Community 74 - "MCPServer"
Cohesion: 0.13
Nodes (4): MCPServer, TestBuiltIns, TestPermissionsDeclaration, TestServeInstallHint

### Community 75 - "ToolVisibilityAuthoriser"
Cohesion: 0.12
Nodes (5): [0.2.0] - 2026-08-21, Added, Fixed, Removed, ToolVisibilityAuthoriser

### Community 76 - ".test_with_the_scope_authoriser"
Cohesion: 0.20
Nodes (5): ReadTool, InputModel, RecordingAuthoriser, TestAuthorise, WriteTool

### Community 77 - "fetching_jwt"
Cohesion: 0.22
Nodes (3): FakeClock, fetching_jwt(), TestJwks

### Community 79 - "sample_tool"
Cohesion: 0.15
Nodes (5): prefix_resolver(), registry(), sample_tool(), spooler_config(), spooler_with_data()

### Community 80 - "PULL_REQUEST_TEMPLATE.md"
Cohesion: 0.40
Nodes (4): Changes, Checklist, Summary, Testing

### Community 82 - "tool_text"
Cohesion: 0.35
Nodes (5): post(), running_werkzeug(), TestRealServer, worker(), tool_text()

### Community 83 - "JwksServer"
Cohesion: 0.24
Nodes (4): jwks_listener(), jwks_server(), JwksServer, JwksState

### Community 84 - "EchoTool"
Cohesion: 0.20
Nodes (4): ApproveTool, EchoTool, InputModel, hide_approve()

### Community 85 - "Project configuration"
Cohesion: 0.25
Nodes (7): CHANGELOG, Checks, Dependency locks, Integration procedure, Project configuration, Publishing, What spindl is

### Community 87 - "Tool Annotations"
Cohesion: 0.29
Nodes (7): Built-in tools, category in _meta, Declaring annotations, How hosts use them, The start-up warning, Tool Annotations, Undeclared hints

### Community 89 - "A lead may write, but only to incident-notes: the tool refuses the rest."
Cohesion: 0.40
Nodes (5): A lead may write, but only to incident-notes: the tool refuses the rest., JwtAuthenticator, Reach fails closed, Reference implementations, ScopeAuthoriser

### Community 91 - "call_wsgi"
Cohesion: 0.27
Nodes (6): call_wsgi(), start_response(), plain_host(), app(), rpc(), TestPlainWsgi

### Community 92 - "Use Cases"
Cohesion: 0.40
Nodes (5): Multiple Servers, One Client, Per-Request Prefixing (HTTP), Same Server, Multiple Instances, Single Server, Single Client, Use Cases

### Community 94 - "test_docs_examples.py"
Cohesion: 0.06
Nodes (18): is_scope_token(), TestTypes, _anchors(), _close_servers(), _Collect, docs_client(), DocsClient, extract() (+10 more)

### Community 97 - "jwt.py"
Cohesion: 0.07
Nodes (7): _check_jwks_url(), JwtAuthenticator, _Key, _NoRedirect, _parse_key_set(), _Refused, ToolAuthoriser

### Community 98 - "AccessTokenIdentity"
Cohesion: 0.22
Nodes (3): Changed, 4. Your 0.4 authentication still works, with a warning, AccessTokenIdentity

### Community 101 - "test_auth_jwt.py"
Cohesion: 0.10
Nodes (10): b64(), claims(), hand_made_token(), jwk_for(), JwksHandler, reach_from_claims(), ReadTool, InputModel (+2 more)

### Community 106 - "jwt_server"
Cohesion: 0.20
Nodes (5): jwt_server(), mcp_client(), raw_initialise(), RecordingAuthoriser, TestEndToEnd

### Community 115 - "Authenticator"
Cohesion: 0.10
Nodes (21): [0.5.0b1] - 2026-11-06, Added, Changed, Tool access and reach are separate controls, A signing key made for this check and thrown away afterwards., A worked example, Authentication and Tool Access, Deprecated 0.4 interfaces (+13 more)

## Knowledge Gaps
- **1 isolated node(s):** `cognisn-spindl`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 654 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **33 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BaseTool` connect `BaseTool` to `SpoolerDistinctTool`, `test_visibility.py`, `GetDevices`, `Spool Storage Backend`, `Registry and Error Modules`, `Tests`, `Registry Lookup`, `sample/server.py`, `.build_http_app`, `ToolRegistry`, `HTTP App Builder`, `test_wsgi.py`, `test_auth_core.py`, `.allows`, `.definitions`, `make_server`, `current_identity`, `Building Tools`, `._step_up_gate`, `ScopeAuthoriser`, `auth/__init__.py`, `.register`, `6. ToolRegistry lookups`, `test_auth_api_key.py`, `SlowTool`, `DescribeToolTool`, `MCPServer`, `ToolVisibilityAuthoriser`, `.test_with_the_scope_authoriser`, `sample_tool`, `EchoTool`, `TestContradiction`, `jwt.py`, `test_auth_jwt.py`, `jwt_server`, `Authenticator`?**
  _High betweenness centrality (0.173) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `MCPServer` (e.g. with `Lifecycle` and `Storage Backends`) actually correct?**
  _`MCPServer` has 47 INFERRED edges - model-reasoned connections that need verification._
- **What connects `cognisn-spindl` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SpoolerDistinctTool` be split into smaller, more focused modules?**
  _Cohesion score 0.05789473684210526 - nodes in this community are weakly interconnected._
- **Why does `MCPServer` connect `MCPServer` to `test_visibility.py`, `in_memory_client`, `Registry and Error Modules`, `.build_sse_app`, `MCPServer`, `sample/server.py`, `.build_http_app`, `HTTP App Builder`, `test_wsgi.py`, `test_auth_core.py`, `.definitions`, `make_server`, `current_identity`, `.wsgi_app`, `make_flask_app`, `._step_up_gate`, `wsgi.py`, `Response Spooler`, `.process_response`, `ScopeAuthoriser`, `.register`, `6. ToolRegistry lookups`, `make_server`, `BaseTool`, `test_auth_api_key.py`, `make_server`, `init_app`, `ToolVisibilityAuthoriser`, `TestContradiction`, `test_docs_examples.py`, `AccessTokenIdentity`, `jwt_server`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Are the 27 inferred relationships involving `BaseTool` (e.g. with `Added` and `Removed`) actually correct?**
  _`BaseTool` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_visibility.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12762762762762764 - nodes in this community are weakly interconnected._