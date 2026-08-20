"""Get detailed usage guide for a specific tool.

Auto-registered by the MCPServer. Returns the fully resolved
guide text for a tool, with all @placeholders replaced by
prefixed wire names.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class DescribeToolTool(BaseTool):
    """Get detailed usage instructions for a specific tool."""

    name = "describe_tool"
    description = "Get detailed usage guide for a specific tool"
    category = "skills"

    class InputModel(BaseModel):
        tool_name: str = Field(
            description=(
                "The full name of the tool to describe " "(as shown by list_tools)"
            ),
        )

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def guide(self) -> str:
        return (
            "# @describe_tool\n\n"
            "Returns detailed usage instructions for a specific tool, "
            "including parameters, examples, and workflow guidance.\n\n"
            "First call @list_tools to see all available tools, then "
            "call @describe_tool with the tool's full name to get "
            "its detailed guide.\n\n"
            "## Parameters\n\n"
            "- **tool_name** (required): The full name of the tool "
            "to describe, as returned by @list_tools\n"
        )

    async def execute(self, **params: Any) -> dict[str, Any]:
        try:
            validated = self.InputModel(**params)

            guide_text = self._registry.get_tool_guide(validated.tool_name)
            if guide_text is None:
                return StructuredError(
                    error=ErrorDetail(
                        error_code="TOOL_NOT_FOUND",
                        error_message=(
                            f"No tool found with name " f"'{validated.tool_name}'"
                        ),
                        retry_eligible=False,
                        suggestion=(
                            "Use the list_tools tool to see all "
                            "available tools and their full names."
                        ),
                    ),
                ).to_dict()

            return {
                "success": True,
                "tool_name": validated.tool_name,
                "guide": guide_text,
            }

        except Exception as exc:
            logger.error("Error describing tool: %s", exc)
            return StructuredError(
                error=ErrorDetail(
                    error_code="INTERNAL_ERROR",
                    error_message=f"Failed to describe tool: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
