"""Sample MCP server demonstrating the spindl framework.

A fictional "inventory" server that manages devices and vulnerabilities.
Showcases:
  - Tool registration with BaseTool subclasses
  - Tool annotations (title, read_only, destructive, idempotent, open_world)
  - Pydantic InputModel for parameter validation
  - Custom guide() with @placeholder references
  - Response spooling for large data sets
  - API key authentication with ApiKeyAuthenticator and ScopeAuthoriser
  - Tool permissions, and reach applied inside every tool
  - Every transport: stdio, HTTP streamable, SSE, and a Flask application

Usage:
    # stdio (default, for Claude Desktop / MCP Inspector); no authentication
    python sample/server.py

    # HTTP streamable transport, with API keys
    python sample/server.py --http --port 8000

    # SSE transport, with API keys
    python sample/server.py --sse --port 8000

    # Mounted in a small Flask application, with API keys
    python sample/server.py --flask --port 8000

On the networked transports the server generates two demo API keys at start-up
and prints them (or writes them to --keys-file). They are synthetic and valid
only until the process stops.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from typing import Optional

from tools.acknowledge_finding import AcknowledgeFindingTool
from tools.get_devices import ALL_LOCATIONS, GetDevicesTool
from tools.get_vulnerabilities import GetVulnerabilitiesTool
from tools.reach import SiteReach

from spindl import AuthConfig, MCPServer, SpoolerConfig
from spindl.auth import (
    ApiKeyAuthenticator,
    ApiKeyRecord,
    InMemoryApiKeyStore,
    ScopeAuthoriser,
    generate_api_key,
    hash_api_key,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# The demo keys' reach: the reader sees two sites and may not write; the
# editor sees every site and may write.
READER_REACH = SiteReach(frozenset({"us-east-1", "eu-west-1"}))
EDITOR_REACH = SiteReach(ALL_LOCATIONS, can_write=True)


def issue_demo_keys(store: InMemoryApiKeyStore) -> dict[str, str]:
    """Generate the two demo keys, store their hashes and return the keys."""
    reader = generate_api_key("inv")
    editor = generate_api_key("inv")
    store.add(
        ApiKeyRecord(
            key_id="demo-reader",
            key_hash=hash_api_key(reader),
            subject="reader@example.com",
            tool_permissions=frozenset({"inventory:read"}),
            reach=READER_REACH,
        )
    )
    store.add(
        ApiKeyRecord(
            key_id="demo-editor",
            key_hash=hash_api_key(editor),
            subject="editor@example.com",
            tool_permissions=frozenset({"inventory:read", "inventory:write"}),
            reach=EDITOR_REACH,
        )
    )
    return {"reader": reader, "editor": editor}


def build_server(
    resource_url: Optional[str] = None,
) -> tuple[MCPServer, dict[str, str]]:
    """Create the sample inventory MCP server and its demo keys.

    With ``resource_url`` (the networked transports) the server requires an
    API key on every request and the demo keys are returned. Without it
    (stdio, one local user) there is no authentication, every tool sees
    every site, and no keys are made.
    """
    keys: dict[str, str] = {}
    auth: Optional[AuthConfig] = None
    local_reach: Optional[SiteReach] = None
    if resource_url is not None:
        store = InMemoryApiKeyStore()
        keys = issue_demo_keys(store)
        authenticator = ApiKeyAuthenticator(store, authoriser=ScopeAuthoriser())
        auth = AuthConfig(
            authenticator=authenticator,
            resource_server_url=resource_url,
            # This server issues its keys itself; the URL names where a
            # client would be told to get one.
            authorization_servers=["https://auth.example.com/"],
            credential_headers=authenticator.credential_headers,
        )
    else:
        local_reach = SiteReach(ALL_LOCATIONS, can_write=True)

    server = MCPServer(
        prefix="inventory",
        spooler=SpoolerConfig(
            db_path=os.environ.get("SPOOLER_DB_PATH")
            or os.path.join(tempfile.gettempdir(), f"spindl_sample_{os.getpid()}.db"),
            max_inline_items=5,
            max_inline_tokens=1000,
            summary_sample_size=3,
        ),
        server_name="sample-inventory",
        auth=auth,
    )

    server.register_all(
        [
            GetDevicesTool(local_reach),
            GetVulnerabilitiesTool(local_reach),
            AcknowledgeFindingTool(local_reach),
        ]
    )

    return server, keys


def announce_keys(keys: dict[str, str], keys_file: Optional[str]) -> None:
    """Hand the demo keys to the person running the sample."""
    if keys_file:
        with open(keys_file, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(keys, handle)
        print(f"Demo API keys written to {keys_file}", file=sys.stderr)
        return
    print(
        "Demo API keys for this run only (synthetic, regenerated at every start).\n"
        "Send one as the X-API-Key header.\n"
        f"  reader (inventory:read; us-east-1 and eu-west-1; read only): "
        f"{keys['reader']}\n"
        f"  editor (inventory:read inventory:write; every site): {keys['editor']}",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample spindl MCP server")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument(
        "--http", action="store_true", help="Use HTTP streamable transport"
    )
    transport.add_argument("--sse", action="store_true", help="Use SSE transport")
    transport.add_argument(
        "--flask", action="store_true", help="Serve from a small Flask application"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Address to listen on (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--keys-file", help="Write the demo API keys to this JSON file instead"
    )
    args = parser.parse_args()

    if not (args.http or args.sse or args.flask):
        server, _ = build_server()
        asyncio.run(server.run_stdio())
        return

    path = "/sse" if args.sse else "/mcp"
    server, keys = build_server(f"http://{args.host}:{args.port}{path}")
    announce_keys(keys, args.keys_file)

    if args.http:
        asyncio.run(server.run_http(host=args.host, port=args.port))
    elif args.sse:
        asyncio.run(server.run_sse(host=args.host, port=args.port))
    else:
        from flask_app import create_app

        create_app(server).run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
