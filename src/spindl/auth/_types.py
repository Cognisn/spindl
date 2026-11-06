"""The types spindl's authentication is built from.

Two controls, decided at different points, come from the same credential:

* **Tool access** answers "may this caller see and call this tool?". spindl
  asks :meth:`Authenticator.authorise` before any tool code runs, and hides
  or refuses the tool when the answer is no.
* **Reach** answers "what may a permitted call touch?" (which tenants,
  accounts, records or hosts). It travels as :attr:`Identity.reach`, opaque
  to spindl, and only the tool can enforce it, by reading
  ``self.context.reach``.

Passing ``authorise()`` never limits what a tool touches. A tool that is
allowed to run still sees whatever its own code reaches unless it applies
the caller's reach itself.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken

    from spindl.tool import BaseTool

ToolAction = Literal["list", "call"]
"""What the caller is doing with a tool: listing it or calling it."""

DenialMode = Literal["hide", "step_up"]
"""How a tool the caller may not use is answered (see ``AuthConfig``)."""

# RFC 6749 section 3.3: scope-token = 1*( %x21 / %x23-5B / %x5D-7E )
_SCOPE_TOKEN = re.compile(r"[\x21\x23-\x5B\x5D-\x7E]+")


def is_scope_token(name: str) -> bool:
    """Whether ``name`` is a valid OAuth 2.0 scope token (RFC 6749 section 3.3)."""
    return isinstance(name, str) and _SCOPE_TOKEN.fullmatch(name) is not None


class TokenVerifier(Protocol):
    """Verifies a bearer token and returns the caller's access token.

    The 0.4.0 interface, kept for compatibility. Mirrors
    ``mcp.server.auth.provider.TokenVerifier`` so adopters can pass the same
    object they would hand to the SDK directly. New code implements
    :class:`Authenticator` instead.
    """

    async def verify_token(self, token: str) -> Optional["AccessToken"]: ...


@dataclass(frozen=True)
class Credentials:
    """What the caller presented with a request, as spindl read it.

    Attributes:
        bearer_token: The token from ``Authorization: Bearer <token>``, or
            ``None`` when the request carries none.
        headers: A read-only mapping of the configured credential header
            names (``AuthConfig.credential_headers``), lower-cased, to the
            values the request carried. Only headers that were present
            appear. ``Authorization`` is never included.

    Neither value is shown by ``repr``, so a ``Credentials`` that reaches a
    log line does not leak a secret.
    """

    bearer_token: Optional[str] = field(default=None, repr=False)
    headers: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )

    def __post_init__(self) -> None:
        frozen = MappingProxyType({k.lower(): v for k, v in self.headers.items()})
        object.__setattr__(self, "headers", frozen)

    @property
    def present(self) -> bool:
        """Whether the request carried any credential spindl reads."""
        return self.bearer_token is not None or bool(self.headers)


@dataclass(frozen=True)
class Identity:
    """The authenticated caller, as returned by :meth:`Authenticator.authenticate`.

    Attributes:
        subject: Who the caller is (a user or service principal). Required
            and non-empty. Spools are confined to it.
        client_id: The client application, when known.
        tool_permissions: The tool permissions this credential grants. A
            tool declaring ``permissions`` may need them (the authenticator
            decides in ``authorise``), and spindl checks
            ``AuthConfig.required_scopes`` against them on every request.
        reach: What this credential's calls may touch, for example a set of
            tenants or accounts. Opaque to spindl, which never reads it; it
            is handed to tools as ``self.context.reach``. ``None`` means the
            credential carries no reach, and with an ``Authenticator``
            configured spindl then refuses every tool that requires reach.
        expires_at: When the credential expires, in seconds since the
            epoch. An expired identity is refused with ``401``.

    Tool access (``tool_permissions``, decided by ``authorise``) and reach
    are separate controls: permission to call a tool never limits what the
    tool touches.
    """

    subject: str
    client_id: Optional[str] = None
    tool_permissions: frozenset[str] = frozenset()
    reach: object = None
    expires_at: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError("Identity.subject must be a non-empty string")
        permissions: Iterable[str] = self.tool_permissions
        if isinstance(permissions, str):
            raise TypeError("Identity.tool_permissions must be a set of names")
        object.__setattr__(self, "tool_permissions", frozenset(permissions))


@dataclass(frozen=True)
class AccessTokenIdentity(Identity):
    """An :class:`Identity` made from a 0.4.0 ``AccessToken``.

    Produced by the ``token_verifier`` adapter so that 0.4.0 tools reading
    ``current_identity().scopes`` (or ``.token``, ``.resource``, ``.claims``)
    keep working. New code should read ``tool_permissions`` instead.
    """

    access_token: Optional["AccessToken"] = field(default=None, repr=False)

    @property
    def scopes(self) -> list[str]:
        """The token's scopes, as ``AccessToken.scopes`` gave them."""
        return list(self.access_token.scopes) if self.access_token else []

    @property
    def token(self) -> Optional[str]:
        """The raw token, as ``AccessToken.token`` gave it (0.4.0 only)."""
        return self.access_token.token if self.access_token else None

    @property
    def resource(self) -> Optional[str]:
        """The token's RFC 8707 resource indicator, when the verifier set it."""
        return self.access_token.resource if self.access_token else None

    @property
    def claims(self) -> Optional[dict[str, Any]]:
        """The token's additional claims, when the verifier set them."""
        return self.access_token.claims if self.access_token else None


@dataclass(frozen=True)
class ToolContext:
    """What a tool knows about the call it is serving, as ``self.context``.

    Attributes:
        identity: The authenticated caller, or ``None`` when authentication
            is off (or on stdio).
        reach: ``identity.reach``: what this call may touch. spindl does not
            enforce it; the tool must apply it to every query it makes.
        instance_prefix: The ``X-Spindl-Prefix`` instance prefix for this
            request, or ``None``.
    """

    identity: Optional[Identity]
    reach: object
    instance_prefix: Optional[str]


@runtime_checkable
class Authenticator(Protocol):
    """Turns a request's credentials into an identity and decides tool access.

    spindl owns the mechanics around it: reading the bearer token and the
    configured headers, the ``401`` and ``403`` challenges, the RFC 9728
    metadata document and filtering tools. An authenticator supplies only
    the two decisions.

    ``authenticate`` returns the caller's :class:`Identity`, or ``None``
    when the credentials are not valid (spindl answers ``401``). It must
    validate everything a resource server is required to, including that
    the credential was issued for this server (audience binding).

    ``authorise`` decides **tool access only**: whether ``identity`` may
    list (``action == "list"``) or call (``action == "call"``) ``tool``. It
    runs before any tool code. It does not and cannot limit what an
    allowed tool touches: that is reach, carried in ``Identity.reach`` and
    enforced by the tool. It may be called several times per request, so
    keep it quick and free of side effects. If it raises, the tool is
    treated as denied.
    """

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]: ...

    async def authorise(
        self, identity: Identity, tool: "BaseTool", action: ToolAction
    ) -> bool: ...
