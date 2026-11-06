"""Authentication configuration for the HTTP and SSE transports."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from spindl.auth._types import Authenticator, DenialMode, TokenVerifier

logger = logging.getLogger("spindl.auth")

DENIAL_MODES: tuple[DenialMode, ...] = ("hide", "step_up")


@dataclass
class AuthConfig:
    """Configuration for authenticating callers on the HTTP and SSE transports.

    spindl is a resource server: it checks credentials an external party
    issued and never issues them. Give exactly one of ``authenticator``
    (0.5.0) or ``token_verifier`` (0.4.0, deprecated).

    Attributes:
        token_verifier: Deprecated. The 0.4.0 object with an async
            ``verify_token(token)`` method. It is wrapped in an adapter that
            keeps 0.4.0 behaviour exactly: the subject comes from the token,
            ``tool_permissions`` from its scopes, reach is ``None`` and the
            reach requirement is off. Logs one deprecation warning.
        resource_server_url: Canonical URL of this MCP endpoint, advertised
            as ``resource`` in the protected-resource metadata. Required.
        authorization_servers: URLs of the authorisation servers clients
            should obtain credentials from. At least one is required.
        required_scopes: Permissions every request must carry, checked
            against ``Identity.tool_permissions``. A request lacking one is
            answered ``403``. Empty means any valid credential is accepted.
        scopes_supported: Scopes advertised in the metadata document, before
            the tools' declared permissions are added. Defaults to
            ``required_scopes``.
        resource_name: Optional human-readable name for the metadata.
        serve_metadata: Serve the RFC 9728 protected-resource metadata
            document. Set False when a gateway already serves it; the ``401``
            and ``403`` challenges are unaffected.
        authenticator: An :class:`~spindl.auth.Authenticator`. It turns the
            credentials into an :class:`~spindl.auth.Identity` and decides
            tool access. With an authenticator configured, every tool
            requires reach unless it sets ``requires_reach = False``.
        credential_headers: Header names spindl reads and passes to the
            authenticator besides ``Authorization: Bearer``, for example
            ``X-API-Key``. Matched case-insensitively and passed lower-cased.
        denial_mode: ``"hide"`` (the default) hides a tool the caller may not
            use from ``tools/list`` and answers a call exactly as for an
            unknown tool. ``"step_up"`` keeps a tool listed when the caller
            lacks only some of its declared permissions, and answers a call
            with ``403`` ``insufficient_scope`` naming the missing ones, so a
            client can ask for them. Other denials are still answered as an
            unknown tool.

    Tool access and reach are separate controls. ``authorise`` decides
    whether a tool may be listed or called; it never limits what an allowed
    tool touches. That is reach, carried on the identity and applied by the
    tool.
    """

    token_verifier: Optional[TokenVerifier] = None
    resource_server_url: str = ""
    authorization_servers: list[str] = field(default_factory=list)
    required_scopes: list[str] = field(default_factory=list)
    scopes_supported: Optional[list[str]] = None
    resource_name: Optional[str] = None
    serve_metadata: bool = True
    authenticator: Optional[Authenticator] = None
    credential_headers: list[str] = field(default_factory=list)
    denial_mode: DenialMode = "hide"

    def __post_init__(self) -> None:
        if self.authenticator is not None and self.token_verifier is not None:
            raise ValueError(
                "AuthConfig takes an authenticator or a token_verifier, not both. "
                "The token_verifier is the deprecated 0.4.0 interface; move its "
                "logic into the authenticator."
            )
        if self.authenticator is None and self.token_verifier is None:
            raise ValueError("AuthConfig requires an authenticator")
        if self.authenticator is not None and not isinstance(
            self.authenticator, Authenticator
        ):
            raise TypeError(
                "AuthConfig.authenticator must provide async authenticate() "
                "and authorise() methods"
            )
        if not self.resource_server_url:
            raise ValueError("AuthConfig requires resource_server_url")
        if not self.authorization_servers:
            raise ValueError(
                "AuthConfig requires at least one authorization server URL"
            )
        if self.denial_mode not in DENIAL_MODES:
            raise ValueError(
                f"AuthConfig.denial_mode must be 'hide' or 'step_up', "
                f"not {self.denial_mode!r}"
            )
        headers = [name.strip().lower() for name in self.credential_headers]
        if any(not name for name in headers):
            raise ValueError("AuthConfig.credential_headers must not be empty")
        if "authorization" in headers:
            raise ValueError(
                "AuthConfig.credential_headers must not name Authorization; "
                "spindl always reads the bearer token from it"
            )
        self.credential_headers = list(dict.fromkeys(headers))
        if self.scopes_supported is None:
            self.scopes_supported = list(self.required_scopes)
        if self.token_verifier is not None:
            logger.warning(
                "AuthConfig(token_verifier=...) is deprecated and will be "
                "removed in a future release. Implement spindl.auth."
                "Authenticator and pass AuthConfig(authenticator=...)."
            )
