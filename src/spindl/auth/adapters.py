"""Adapters that keep the 0.4.0 ``token_verifier`` and ``tool_visibility`` working.

Both wrap the 0.4.0 interface in an :class:`~spindl.auth.Authenticator`
with 0.4.0 behaviour exactly: the subject comes from the token,
``tool_permissions`` from its scopes, reach is ``None`` and spindl does not
require reach. Both interfaces are deprecated; new code implements
``Authenticator`` directly.
"""

import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from spindl.auth._types import (
    AccessTokenIdentity,
    Credentials,
    Identity,
    TokenVerifier,
    ToolAction,
)

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken

    from spindl.tool import BaseTool

LegacyVisibility = Callable[[Optional["AccessToken"], "BaseTool"], bool]

_registry_logger = logging.getLogger("spindl.registry")


def identity_from_access_token(token: "AccessToken") -> Optional[AccessTokenIdentity]:
    """The identity a 0.4.0 ``AccessToken`` stands for, with 0.4.0 meaning.

    Subject from the token (its client id when it names no subject),
    ``tool_permissions`` from its scopes, and no reach. ``None`` when the
    token names neither a subject nor a client.
    """
    subject = token.subject or token.client_id
    if not subject:
        return None
    return AccessTokenIdentity(
        subject=subject,
        client_id=token.client_id,
        tool_permissions=frozenset(token.scopes),
        reach=None,
        expires_at=token.expires_at,
        access_token=token,
    )


class ToolVisibilityAuthoriser:
    """Wraps a 0.4.0 ``tool_visibility`` hook as an authoriser.

    The hook receives the caller's ``AccessToken`` (or ``None`` when
    authentication is off), exactly as in 0.4.0, and governs listing and
    calling alike. A hook that raises hides the tool and logs a warning.
    ``authenticate`` accepts no one: the hook only ever decides access.
    """

    def __init__(self, hook: LegacyVisibility) -> None:
        self.hook = hook

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        return None

    async def authorise(
        self, identity: Optional[Identity], tool: "BaseTool", action: ToolAction
    ) -> bool:
        return self.check(identity, tool)

    def check(self, identity: Optional[Identity], tool: "BaseTool") -> bool:
        """The hook's decision, made synchronously, failing closed."""
        token = (
            identity.access_token if isinstance(identity, AccessTokenIdentity) else None
        )
        try:
            return bool(self.hook(token, tool))
        except Exception:
            _registry_logger.warning(
                "Tool visibility hook failed for '%s'; hiding the tool",
                tool.name,
                exc_info=True,
            )
            return False


class TokenVerifierAuthenticator:
    """Wraps a 0.4.0 ``TokenVerifier`` (and optional visibility hook).

    ``authenticate`` verifies the bearer token and returns an
    :class:`~spindl.auth.AccessTokenIdentity`: subject from the token's
    ``subject`` (its ``client_id`` when the verifier set none),
    ``tool_permissions`` from its scopes, reach ``None``. Configured header
    credentials are ignored, as in 0.4.0. ``authorise`` applies the
    visibility hook when there is one and otherwise allows every tool.
    """

    def __init__(
        self,
        verifier: TokenVerifier,
        visibility: Optional[LegacyVisibility] = None,
    ) -> None:
        self.verifier = verifier
        self.visibility = (
            ToolVisibilityAuthoriser(visibility) if visibility is not None else None
        )

    async def authenticate(self, credentials: Credentials) -> Optional[Identity]:
        if credentials.bearer_token is None:
            return None
        token: Any = await self.verifier.verify_token(credentials.bearer_token)
        if not token:
            return None
        if token.expires_at and token.expires_at < int(time.time()):
            return None
        return identity_from_access_token(token)

    async def authorise(
        self, identity: Optional[Identity], tool: "BaseTool", action: ToolAction
    ) -> bool:
        if self.visibility is None:
            return True
        return self.visibility.check(identity, tool)
