"""Sample MCP server demonstrating the spindl framework.

A fictional "inventory" server that manages devices and vulnerabilities.
Showcases:
  - Tool registration with BaseTool subclasses
  - Pydantic InputModel for parameter validation
  - Custom guide() with @placeholder references
  - Response spooling for large data sets
  - All three transports (stdio, HTTP, SSE)

Usage:
    # stdio (default, for Claude Desktop / MCP Inspector)
    python sample/server.py

    # HTTP streamable transport
    python sample/server.py --http --port 8000

    # SSE transport
    python sample/server.py --sse --port 8000
"""

import argparse
import asyncio
import logging

from spindl import MCPServer, SpoolerConfig

from tools.get_devices import GetDevicesTool
from tools.get_vulnerabilities import GetVulnerabilitiesTool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def build_server() -> MCPServer:
    """Create and configure the sample inventory MCP server."""
    server = MCPServer(
        prefix="inventory",
        spooler=SpoolerConfig(
            db_path="/tmp/sample_spooler.db",
            max_inline_items=5,
            max_inline_tokens=1000,
            summary_sample_size=3,
        ),
        server_name="sample-inventory",
    )

    server.register_all([
        GetDevicesTool(),
        GetVulnerabilitiesTool(),
    ])

    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample spindl MCP server"
    )
    parser.add_argument(
        "--http", action="store_true", help="Use HTTP streamable transport"
    )
    parser.add_argument(
        "--sse", action="store_true", help="Use SSE transport"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for HTTP/SSE (default: 8000)"
    )
    args = parser.parse_args()

    server = build_server()

    if args.http:
        asyncio.run(server.run_http(port=args.port))
    elif args.sse:
        asyncio.run(server.run_sse(port=args.port))
    else:
        asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
