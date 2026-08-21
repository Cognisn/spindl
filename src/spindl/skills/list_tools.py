"""List all available tools in this MCP server.

Auto-registered by the MCPServer. Returns all tools grouped by
category with their prefixed wire names and descriptions.
"""

import logging
from typing import Any

from spindl.responses import ResponseEnvelope, ResponseMetadata
from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class ListToolsTool(BaseTool):
    """List all available tools with their names and descriptions."""

    name = "list_tools"
    description = "List all available tools with name, category, and description"
    category = "skills"

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def guide(self) -> str:
        return (
            "# @list_tools\n\n"
            "Returns all available tools in this MCP server, grouped "
            "by category. Each entry includes the tool's full name "
            "(which you should use when calling it), its category, "
            "and a short description.\n\n"
            "Use @describe_tool to get detailed usage instructions "
            "for a specific tool.\n\n"
            "## Parameters\n\n"
            "*No parameters required.*\n"
        )

    async def execute(self, **params: Any) -> dict[str, Any]:
        try:
            tools = self._registry.list_tools_metadata()

            # Group by category
            categories: dict[str, list[dict[str, Any]]] = {}
            for tool in tools:
                cat = tool["category"]
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                    }
                )

            return ResponseEnvelope(
                success=True,
                data={
                    "total_tools": len(tools),
                    "categories": categories,
                },
                metadata=ResponseMetadata(
                    total_results=len(tools),
                    returned_results=len(tools),
                    truncated=False,
                ),
            ).to_dict()

        except Exception as exc:
            logger.exception("Error listing tools: %s", exc)
            return StructuredError(
                error=ErrorDetail(
                    error_code="INTERNAL_ERROR",
                    error_message=f"Failed to list tools: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
