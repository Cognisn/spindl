"""The sample inventory server mounted in a small Flask application.

Flask keeps its own routes; requests under /mcp go to spindl through the
WSGI bridge, with authentication, prefixing and tool access unchanged. Needs
the wsgi extra and Flask: pip install "cognisn-spindl[wsgi]" flask
"""

from flask import Flask

from spindl import MCPServer
from spindl.wsgi import init_app


def create_app(server: MCPServer) -> Flask:
    """A Flask application with a home page and the MCP server at /mcp."""
    app = Flask(__name__)

    @app.get("/")
    def home() -> str:
        return "Sample inventory. The MCP endpoint is at /mcp.\n"

    # Mounts the endpoint at /mcp and, because the server serves RFC 9728
    # metadata, /.well-known/oauth-protected-resource/mcp too.
    init_app(app, server, path="/mcp")
    return app
