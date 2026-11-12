"""Reach for the sample inventory server: which sites a caller's calls touch.

spindl never reads reach; it hands it to each tool as ``self.context.reach``.
Tool access (may this caller call the tool?) is decided before the tool
runs. Reach (what may the call touch?) is applied by the tool, to every read
and every write, which is what :func:`caller_reach` and the tools that use
it do.
"""

from dataclasses import dataclass
from typing import Any, Optional

from spindl import BaseTool, ErrorDetail, StructuredError


@dataclass(frozen=True)
class SiteReach:
    """The sites (AWS regions in the sample data) a credential may touch."""

    locations: frozenset[str]
    can_write: bool = False


class ReachAwareTool(BaseTool):
    """A sample tool that applies the caller's reach.

    ``local_reach`` is the reach to use when the server runs without
    authentication (stdio, one local user). On an authenticated server it is
    ``None``: there, spindl refuses the call before the tool runs when the
    credential carries no reach, and the tool refuses anything that is not a
    :class:`SiteReach`.
    """

    def __init__(self, local_reach: Optional[SiteReach] = None) -> None:
        self._local_reach = local_reach

    def caller_reach(self) -> Optional[SiteReach]:
        context = self.context
        reach = context.reach if context is not None else None
        if reach is None and (context is None or context.identity is None):
            reach = self._local_reach
        return reach if isinstance(reach, SiteReach) else None


def out_of_reach(message: str) -> dict[str, Any]:
    """The structured refusal a tool returns for a request outside reach."""
    return StructuredError(
        error=ErrorDetail(
            error_code="OUT_OF_REACH",
            error_message=message,
            retry_eligible=False,
            suggestion="Ask for a key whose reach covers the site.",
        ),
    ).to_dict()
