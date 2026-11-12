"""A reference authoriser that grants tool access by declared permissions.

:class:`ScopeAuthoriser` answers the tool-access half of an
:class:`~spindl.auth.Authenticator`: a tool is allowed when the caller's
``Identity.tool_permissions`` include every permission the tool declares
in ``BaseTool.permissions``. A tool that declares no permissions is allowed
for any authenticated identity.

It is meant to be composed, not subclassed. Any authenticator, including a
product's own, can hand its ``authorise`` to one::

    class ProductAuthenticator:
        def __init__(self) -> None:
            self.scopes = ScopeAuthoriser()

        async def authenticate(self, credentials):
            ...  # the product's own credential check

        async def authorise(self, identity, tool, action):
            return await self.scopes.authorise(identity, tool, action)

and :class:`~spindl.auth.api_key.ApiKeyAuthenticator` takes one as its
``authoriser`` argument.

This decides tool access only. It never limits what an allowed tool
touches: that is reach, carried in ``Identity.reach`` and applied by the
tool itself through ``self.context.reach``.
"""

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from spindl.auth._types import Identity, ToolAction

if TYPE_CHECKING:
    from spindl.tool import BaseTool


@runtime_checkable
class Authoriser(Protocol):
    """The tool-access half of an :class:`~spindl.auth.Authenticator`.

    ``authorise`` returns whether ``identity`` may list (``action ==
    "list"``) or call (``action == "call"``) ``tool``. It may be called
    several times per request, so keep it quick and free of side effects.
    """

    async def authorise(
        self, identity: Optional[Identity], tool: "BaseTool", action: ToolAction
    ) -> bool: ...


class ScopeAuthoriser:
    """Allows a tool when the identity holds every permission it declares.

    * A tool whose ``permissions`` are all in ``identity.tool_permissions``
      is allowed, for listing and calling alike.
    * A tool that lacks even one of them is refused. With
      ``AuthConfig(denial_mode="step_up")`` spindl then answers a call with
      ``403 insufficient_scope`` naming the missing permissions.
    * A tool that declares no permissions is allowed for any authenticated
      identity.
    * With no identity (``None``) every tool is refused.
    """

    async def authorise(
        self, identity: Optional[Identity], tool: "BaseTool", action: ToolAction
    ) -> bool:
        if identity is None:
            return False
        return all(name in identity.tool_permissions for name in tool.permissions)

    def __repr__(self) -> str:
        return "ScopeAuthoriser()"
