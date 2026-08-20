"""Resource-server authentication for the HTTP and SSE transports.

Spindl verifies bearer tokens that an external authorisation server has
already issued. It does not implement the authorisation server itself
(login, consent, client registration, or token issue). The heavy lifting
is delegated to the ``mcp`` SDK's auth primitives; this module wires them
into the Starlette applications that the transports build and exposes
the caller's identity to tools through a per-request context accessor.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Protocol

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken


class TokenVerifier(Protocol):
    """Verifies a bearer token and returns the caller's access token.

    Mirrors ``mcp.server.auth.provider.TokenVerifier`` so adopters can pass
    the same object they would hand to the SDK directly.
    """

    async def verify_token(self, token: str) -> Optional["AccessToken"]: ...


@dataclass
class AuthConfig:
    """Configuration for resource-server token verification.

    Attributes:
        token_verifier: Object with an async ``verify_token(token)`` method
            returning an ``AccessToken`` for a valid token, or ``None``.
        resource_server_url: Canonical URL of this MCP endpoint, advertised
            as ``resource`` in the protected-resource metadata.
        authorization_servers: URLs of the authorisation servers clients
            should obtain tokens from. At least one is required.
        required_scopes: Scopes every request must carry. Empty means any
            valid token is accepted.
        scopes_supported: Scopes advertised in the metadata document.
            Defaults to ``required_scopes``.
        resource_name: Optional human-readable name for the metadata.
        serve_metadata: Register the RFC 9728 protected-resource metadata
            routes on the transport application. Set False when a gateway
            already serves the document at the origin; token verification
            and the ``401``/``403`` challenges are unaffected.
    """

    token_verifier: TokenVerifier
    resource_server_url: str
    authorization_servers: list[str]
    required_scopes: list[str] = field(default_factory=list)
    scopes_supported: Optional[list[str]] = None
    resource_name: Optional[str] = None
    serve_metadata: bool = True

    def __post_init__(self) -> None:
        if not self.authorization_servers:
            raise ValueError(
                "AuthConfig requires at least one authorization server URL"
            )
        if self.scopes_supported is None:
            self.scopes_supported = list(self.required_scopes)


METADATA_PATH = "/.well-known/oauth-protected-resource"


def current_identity() -> Optional["AccessToken"]:
    """Return the authenticated caller for the current request.

    Returns ``None`` outside a request or when authentication is not
    enabled. Safe to call from ``BaseTool.execute``.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except ImportError:  # pragma: no cover - mcp is a hard dependency
        return None
    return get_access_token()


def protect(app: Any, config: AuthConfig) -> Any:
    """Wrap an ASGI endpoint with the full bearer-token stack.

    The returned callable authenticates the bearer token, publishes the
    caller for :func:`current_identity`, and then requires a valid token
    with the configured scopes. Unauthenticated requests receive ``401``
    with a ``WWW-Authenticate`` challenge that points at the
    protected-resource metadata document; authenticated requests lacking a
    required scope receive ``403``. Because the stack is self-contained,
    the endpoint can be registered directly on another application's
    router without app-level middleware.
    """
    from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
    from mcp.server.auth.middleware.bearer_auth import (
        BearerAuthBackend,
        RequireAuthMiddleware,
    )
    from pydantic import AnyHttpUrl
    from starlette.middleware.authentication import AuthenticationMiddleware

    guarded = RequireAuthMiddleware(
        app,
        required_scopes=list(config.required_scopes),
        resource_metadata_url=AnyHttpUrl(_metadata_url(config)),
    )
    return AuthenticationMiddleware(
        AuthContextMiddleware(guarded),
        backend=BearerAuthBackend(config.token_verifier),
    )


def metadata_routes(config: AuthConfig) -> list[Any]:
    """Routes serving the RFC 9728 protected-resource metadata document."""
    from mcp.server.auth.routes import create_protected_resource_routes
    from pydantic import AnyHttpUrl

    return create_protected_resource_routes(
        resource_url=AnyHttpUrl(config.resource_server_url),
        authorization_servers=[AnyHttpUrl(u) for u in config.authorization_servers],
        scopes_supported=config.scopes_supported,
        resource_name=config.resource_name,
    )


def _metadata_url(config: AuthConfig) -> str:
    from urllib.parse import urlsplit, urlunsplit

    # RFC 9728 section 3: when the resource URL has a path, the metadata
    # document lives at the well-known prefix followed by that path. This
    # matches the route the mcp SDK registers.
    parts = urlsplit(config.resource_server_url)
    path = METADATA_PATH + parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
