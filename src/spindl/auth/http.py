"""The HTTP mechanics spindl owns: credentials, challenges and metadata.

An :class:`~spindl.auth.Authenticator` supplies two decisions. Everything
around them happens here: reading the bearer token and the configured
credential headers, answering ``401`` with the RFC 9728 challenge,
checking ``required_scopes``, answering ``403`` (``insufficient_scope``),
publishing the identity for :func:`~spindl.auth.current_identity` and
serving the protected-resource metadata document.

No credential, token or header value is ever logged.
"""

import json
import logging
import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlsplit, urlunsplit

from spindl.auth._context import reset_identity, set_identity
from spindl.auth._types import AccessTokenIdentity, Authenticator, Credentials, Identity
from spindl.auth.config import AuthConfig

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken

logger = logging.getLogger("spindl.auth")

METADATA_PATH = "/.well-known/oauth-protected-resource"


def resolve_authenticator(config: AuthConfig) -> Authenticator:
    """The authenticator a config describes, wrapping a 0.4.0 token verifier."""
    if config.authenticator is not None:
        return config.authenticator
    from spindl.auth.adapters import TokenVerifierAuthenticator

    assert config.token_verifier is not None
    return TokenVerifierAuthenticator(config.token_verifier)


def read_credentials(scope: Any, header_names: Iterable[str]) -> Credentials:
    """Read the bearer token and the configured credential headers from a scope."""
    wanted = {name.lower() for name in header_names}
    bearer: Optional[str] = None
    found: dict[str, str] = {}
    for raw_key, raw_value in scope.get("headers", []):
        key = raw_key.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        if key == "authorization":
            if bearer is None and value[:7].lower() == "bearer ":
                bearer = value[7:].strip() or None
        elif key in wanted and key not in found and value:
            found[key] = value
    return Credentials(bearer_token=bearer, headers=found)


def metadata_url(config: AuthConfig) -> str:
    """The URL of the protected-resource metadata document for ``config``.

    RFC 9728 section 3: when the resource URL has a path, the document lives
    at the well-known prefix followed by that path. This matches the route
    the mcp SDK registers.
    """
    parts = urlsplit(config.resource_server_url)
    path = METADATA_PATH + parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


# The 0.4.0 name, kept because other modules imported it.
_metadata_url = metadata_url


def challenge(
    config: AuthConfig,
    error: str,
    description: str,
    scope: Optional[Iterable[str]] = None,
) -> str:
    """Build a ``WWW-Authenticate`` value for a ``401`` or ``403`` answer."""
    parts = [f'error="{error}"', f'error_description="{description}"']
    if scope is not None:
        parts.append(f'scope="{" ".join(scope)}"')
    parts.append(f'resource_metadata="{metadata_url(config)}"')
    return "Bearer " + ", ".join(parts)


async def send_auth_error(
    send: Any,
    config: AuthConfig,
    status: int,
    error: str,
    description: str,
    scope: Optional[Iterable[str]] = None,
) -> None:
    """Answer a request with an RFC 6750 error and its challenge."""
    scopes = list(scope) if scope is not None else None
    body: dict[str, Any] = {"error": error, "error_description": description}
    if scopes is not None:
        body["scope"] = " ".join(scopes)
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                (
                    b"www-authenticate",
                    challenge(config, error, description, scopes).encode(),
                ),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class _Protected:
    """The ASGI stack :func:`protect` returns."""

    def __init__(
        self, app: Any, config: AuthConfig, authenticator: Authenticator
    ) -> None:
        self.app = app
        self.config = config
        self.authenticator = authenticator

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        credentials = read_credentials(scope, self.config.credential_headers)
        if not credentials.present:
            await send_auth_error(
                send, self.config, 401, "invalid_token", "Authentication required"
            )
            return
        identity = await self._authenticate(credentials)
        if identity is None:
            await send_auth_error(
                send, self.config, 401, "invalid_token", "Authentication required"
            )
            return
        for required in self.config.required_scopes:
            if required not in identity.tool_permissions:
                await send_auth_error(
                    send,
                    self.config,
                    403,
                    "insufficient_scope",
                    f"Required scope: {required}",
                )
                return
        await self._call_as(identity, scope, receive, send)

    async def _authenticate(self, credentials: Credentials) -> Optional[Identity]:
        try:
            identity = await self.authenticator.authenticate(credentials)
        except Exception as exc:
            # The exception text may quote the credential, so only its type
            # is logged.
            logger.warning(
                "Authenticator raised %s; refusing the request",
                type(exc).__name__,
            )
            return None
        if identity is None:
            return None
        if not isinstance(identity, Identity):
            logger.warning(
                "Authenticator returned %s, not an Identity; refusing the request",
                type(identity).__name__,
            )
            return None
        if identity.expires_at is not None and identity.expires_at < time.time():
            return None
        return identity

    async def _call_as(
        self, identity: Identity, scope: Any, receive: Any, send: Any
    ) -> None:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
        from starlette.authentication import AuthCredentials

        # The SDK binds an SSE session to the principal that opened it, read
        # from scope["user"], so the identity is presented in that form too.
        user = AuthenticatedUser(_sdk_access_token(identity))
        scope["user"] = user
        scope["auth"] = AuthCredentials(sorted(identity.tool_permissions))
        identity_token = set_identity(identity)
        # 0.4.0 published the SDK's own accessor as well; the adapter keeps it.
        sdk_token = (
            auth_context_var.set(user)
            if isinstance(identity, AccessTokenIdentity)
            else None
        )
        try:
            await self.app(scope, receive, send)
        finally:
            if sdk_token is not None:
                auth_context_var.reset(sdk_token)
            reset_identity(identity_token)


def _sdk_access_token(identity: Identity) -> "AccessToken":
    """The SDK ``AccessToken`` that stands for ``identity`` inside the SDK.

    The 0.4.0 adapter's own token is used as it is. For any other identity a
    stand-in is built that carries no credential: only the principal (client
    and subject) and the permissions.
    """
    if isinstance(identity, AccessTokenIdentity) and identity.access_token is not None:
        return identity.access_token
    from mcp.server.auth.provider import AccessToken

    return AccessToken(
        token="",
        client_id=identity.client_id or identity.subject,
        scopes=sorted(identity.tool_permissions),
        subject=identity.subject,
    )


def protect(
    app: Any, config: AuthConfig, authenticator: Optional[Authenticator] = None
) -> Any:
    """Wrap an ASGI endpoint with spindl's authentication stack.

    The returned callable reads the credentials, asks the authenticator for
    the caller's identity, publishes it for
    :func:`~spindl.auth.current_identity`, and requires every
    ``required_scopes`` permission. A request with no credential, or one the
    authenticator does not accept (or whose identity has expired), receives
    ``401`` with a ``WWW-Authenticate`` challenge pointing at the
    protected-resource metadata document; one lacking a required scope
    receives ``403`` ``insufficient_scope``. The stack is self-contained, so
    the endpoint can be registered directly on another application's router.
    """
    return _Protected(app, config, authenticator or resolve_authenticator(config))


def metadata_routes(
    config: AuthConfig,
    tool_permissions: Optional[Callable[[], Iterable[str]]] = None,
) -> list[Any]:
    """Routes serving the RFC 9728 protected-resource metadata document.

    ``resource`` and ``authorization_servers`` are served exactly as
    configured. Clients compare them as strings (the issuer in particular
    must match the authorisation server's own metadata), so they are not
    passed through URL normalisation, which would add a trailing slash.
    ``scopes_supported`` is the configured scopes together with every
    permission ``tool_permissions()`` names, sorted and de-duplicated, read
    on each request so tools registered later are included.
    """
    from mcp.server.auth.routes import cors_middleware
    from mcp.shared.auth import ProtectedResourceMetadata
    from pydantic import AnyHttpUrl
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    configured = list(config.scopes_supported or [])
    # Validated through the SDK model, then the configured strings restored.
    model = ProtectedResourceMetadata(
        resource=AnyHttpUrl(config.resource_server_url),
        authorization_servers=[AnyHttpUrl(u) for u in config.authorization_servers],
        scopes_supported=configured,
        resource_name=config.resource_name,
    )
    base = model.model_dump(mode="json", exclude_none=True)
    base["resource"] = config.resource_server_url
    base["authorization_servers"] = list(config.authorization_servers)

    def document() -> dict[str, Any]:
        doc = dict(base)
        extra = list(tool_permissions()) if tool_permissions is not None else []
        scopes = sorted(set(configured) | set(extra))
        if scopes or "scopes_supported" in base:
            doc["scopes_supported"] = scopes
        return doc

    async def handle(request: Request) -> Response:
        return JSONResponse(
            document(), headers={"Cache-Control": "public, max-age=3600"}
        )

    path = urlsplit(metadata_url(config)).path
    return [
        Route(
            path,
            endpoint=cors_middleware(handle, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        )
    ]
