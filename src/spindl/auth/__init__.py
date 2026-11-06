"""Authentication and tool access for the HTTP and SSE transports.

spindl is a resource server: it checks credentials that something else
issued. An :class:`Authenticator` turns a request's :class:`Credentials`
into an :class:`Identity` and decides tool access; spindl owns the rest
(reading credentials, the ``401`` and ``403`` challenges, the RFC 9728
metadata document and filtering tools).

**Tool access is not reach.** Tool access (may this caller see and call
this tool?) is decided by ``Authenticator.authorise()`` before any tool
code runs. Reach (what may a permitted call touch?) comes from the same
credential as ``Identity.reach``, but only the tool can enforce it, by
reading ``self.context.reach``. Passing ``authorise()`` never limits what a
tool touches. With an authenticator configured, spindl refuses to run a
tool that requires reach when the credential carries none.

Every name the 0.4.0 ``spindl.auth`` module exported is still exported
here.
"""

from spindl.auth._context import current_identity, current_tool_context
from spindl.auth._types import (
    AccessTokenIdentity,
    Authenticator,
    Credentials,
    DenialMode,
    Identity,
    TokenVerifier,
    ToolAction,
    ToolContext,
    is_scope_token,
)
from spindl.auth.adapters import TokenVerifierAuthenticator, ToolVisibilityAuthoriser
from spindl.auth.api_key import (
    ApiKeyAuthenticator,
    ApiKeyRecord,
    ApiKeyStore,
    InMemoryApiKeyStore,
    generate_api_key,
    hash_api_key,
)
from spindl.auth.config import AuthConfig
from spindl.auth.http import (
    METADATA_PATH,
    _metadata_url,
    metadata_routes,
    metadata_url,
    protect,
)
from spindl.auth.scopes import Authoriser, ScopeAuthoriser

__all__ = [
    "AccessTokenIdentity",
    "ApiKeyAuthenticator",
    "ApiKeyRecord",
    "ApiKeyStore",
    "AuthConfig",
    "Authenticator",
    "Authoriser",
    "Credentials",
    "DenialMode",
    "Identity",
    "InMemoryApiKeyStore",
    "METADATA_PATH",
    "ScopeAuthoriser",
    "TokenVerifier",
    "TokenVerifierAuthenticator",
    "ToolAction",
    "ToolContext",
    "ToolVisibilityAuthoriser",
    "_metadata_url",
    "current_identity",
    "current_tool_context",
    "generate_api_key",
    "hash_api_key",
    "is_scope_token",
    "metadata_routes",
    "metadata_url",
    "protect",
]
