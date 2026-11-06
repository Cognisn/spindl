"""Per-request state: the caller's identity and the running tool's context.

Both live in context variables because one server, and one tool instance,
serves many requests at once. Each request (and each tool call) runs in its
own context, so concurrent calls never see each other's values.
"""

from contextvars import ContextVar, Token
from typing import Optional

from spindl.auth._types import Identity, ToolContext

_identity_var: ContextVar[Optional[Identity]] = ContextVar(
    "spindl_identity", default=None
)
_tool_context_var: ContextVar[Optional[ToolContext]] = ContextVar(
    "spindl_tool_context", default=None
)


def current_identity() -> Optional[Identity]:
    """Return the authenticated caller for the current request.

    Returns the :class:`Identity` the authenticator produced, or ``None``
    outside a request or when authentication is not enabled. Safe to call
    from ``BaseTool.execute``. With the 0.4.0 ``token_verifier`` adapter the
    value is an :class:`AccessTokenIdentity`, which still offers the
    ``scopes`` and ``token`` attributes 0.4.0 tools read.

    When spindl did not authenticate the request but the mcp SDK's own auth
    middleware did (a host that wraps the endpoint itself, as 0.4.0
    allowed), the SDK's access token is returned in the same form.
    """
    identity = _identity_var.get()
    if identity is not None:
        return identity
    return _from_sdk_context()


def _from_sdk_context() -> Optional[Identity]:
    from mcp.server.auth.middleware.auth_context import get_access_token

    from spindl.auth.adapters import identity_from_access_token

    token = get_access_token()
    return identity_from_access_token(token) if token is not None else None


def set_identity(identity: Optional[Identity]) -> Token[Optional[Identity]]:
    """Publish ``identity`` for the current context; returns a reset token."""
    return _identity_var.set(identity)


def reset_identity(token: Token[Optional[Identity]]) -> None:
    """Restore the identity that was current before :func:`set_identity`."""
    _identity_var.reset(token)


def current_tool_context() -> Optional[ToolContext]:
    """Return the :class:`ToolContext` of the tool call running now, or ``None``."""
    return _tool_context_var.get()


def set_tool_context(context: Optional[ToolContext]) -> Token[Optional[ToolContext]]:
    """Publish ``context`` for the current tool call; returns a reset token."""
    return _tool_context_var.set(context)


def reset_tool_context(token: Token[Optional[ToolContext]]) -> None:
    """Restore the tool context that was current before :func:`set_tool_context`."""
    _tool_context_var.reset(token)
