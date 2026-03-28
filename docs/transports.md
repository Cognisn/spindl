# Transports

Spindl supports three MCP transport mechanisms. Your tools don't change -- only the `run_*()` method differs.

## stdio

Standard I/O transport. The server reads from stdin and writes to stdout.

```python
asyncio.run(server.run_stdio())
```

**Use when:**
- Connecting to local MCP clients (Claude Desktop, Cursor, VS Code, JetBrains)
- Running as a subprocess spawned by the client
- Single-client scenarios

**Configuration in Claude Desktop (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "secops": {
      "command": "python",
      "args": ["-m", "my_secops_server"],
      "env": {
        "SPINDL_INSTANCE_PREFIX": "prod"
      }
    }
  }
}
```

## HTTP Streamable

HTTP-based transport using the MCP SDK's streamable HTTP protocol.

```python
asyncio.run(server.run_http(host="0.0.0.0", port=8000))
```

**Requires:** `pip install spindl[http]` (installs `uvicorn`)

**Use when:**
- Deploying as a networked service
- Running in containers (Docker, Kubernetes)
- Multi-client scenarios
- Per-request instance prefixing is needed

**Endpoint:** `POST /mcp`

### Instance Prefix Header

The HTTP transport reads the `X-Spindl-Prefix` header from each request:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "X-Spindl-Prefix: prod" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

Each request can have a different prefix. Concurrent requests are isolated via `contextvars`.

### Docker Deployment

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install spindl[http]
ENV SPINDL_INSTANCE_PREFIX=prod
EXPOSE 8000
CMD ["python", "-m", "my_server"]
```

```python
# my_server/__main__.py
import asyncio
from my_server.app import create_server

server = create_server()
asyncio.run(server.run_http(host="0.0.0.0", port=8000))
```

## SSE (Server-Sent Events)

SSE transport for streaming connections.

```python
asyncio.run(server.run_sse(host="0.0.0.0", port=8000))
```

**Requires:** `pip install spindl[http]` (installs `uvicorn`)

**Use when:**
- Clients that support SSE but not HTTP streamable
- Streaming updates are needed

**Endpoints:**
- `GET /sse` -- SSE connection endpoint
- `POST /messages/` -- Message posting endpoint

### Instance Prefix Header

Same as HTTP transport -- reads `X-Spindl-Prefix` from the initial SSE connection request.

## Choosing a Transport

| Transport | Clients | Scaling | Auth | Instance Prefix |
|-----------|---------|---------|------|-----------------|
| stdio | Local only | Single client | N/A | Env var only |
| HTTP | Networked | Multi-client | Custom middleware | Header + env var |
| SSE | Networked | Multi-client | Custom middleware | Header + env var |

### Recommendation

- **Development / local use:** stdio
- **Production deployment:** HTTP streamable
- **Legacy client compatibility:** SSE

## Multi-Transport Entrypoint

You can support multiple transports with a command-line argument:

```python
import asyncio
import sys
from spindl import MCPServer, SpoolerConfig

def main():
    server = MCPServer(
        prefix="secops",
        spooler=SpoolerConfig(),
    )
    # Register your tools
    server.register(...)

    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    if transport == "stdio":
        asyncio.run(server.run_stdio())
    elif transport == "http":
        asyncio.run(server.run_http(port=8000))
    elif transport == "sse":
        asyncio.run(server.run_sse(port=8000))
    else:
        print(f"Unknown transport: {transport}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

```bash
python my_server.py stdio   # Local
python my_server.py http    # Networked
python my_server.py sse     # SSE
```
