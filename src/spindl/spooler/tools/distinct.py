"""Get distinct values for a column in spooled data."""

import logging
from typing import Any

from pydantic import BaseModel, Field

from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class SpoolerDistinctTool(BaseTool):
    """Get distinct values and frequency counts for a column."""

    name = "spooler_distinct"
    description = (
        "Get distinct values and frequency counts for a column in spooled data"
    )
    category = "spooler"

    class InputModel(BaseModel):
        spool_id: str = Field(
            description=(
                "The spool_id from the spooled_data summary returned "
                "by the original tool call"
            ),
        )
        column: str = Field(
            description="Column to get distinct values for",
        )
        limit: int = Field(
            default=50,
            description="Maximum distinct values to return",
            ge=1,
            le=500,
        )

    def __init__(self, spooler: Any) -> None:
        self._spooler = spooler

    def guide(self) -> str:
        return (
            "# @spooler_distinct\n\n"
            "**Category:** spooler\n"
            "**Description:** Get distinct values and frequency counts "
            "for a column in spooled data\n\n"
            "## Parameters\n\n"
            "- **spool_id** (required): The spool_id from the "
            "spooled_data summary\n"
            "- **column** (required): Column name to get distinct "
            "values for\n"
            "- **limit** (optional): Max values to return, 1-500 "
            "(default: 50)\n\n"
            "## Usage\n\n"
            "Use this tool to discover unique values in a column "
            "before constructing filter queries. Results are sorted "
            "by frequency (most common first).\n\n"
            "## Examples\n\n"
            "### Discover all severity levels\n"
            '```json\n{"spool_id": "SPOOL_ID", '
            '"column": "severity"}\n```\n\n'
            "## Typical Workflow\n\n"
            "1. Call a data tool -- receive spool_id\n"
            "2. Use @spooler_distinct to explore column values\n"
            "3. Use @spooler_query with filters based on values\n"
            "4. Use @spooler_aggregate for summary statistics\n"
        )

    async def execute(self, **params: Any) -> dict[str, Any]:
        try:
            validated = self.InputModel(**params)
            self._spooler.require_initialised()

            result: dict[str, Any] = await self._spooler.backend.distinct(
                spool_id=validated.spool_id,
                scope=self._spooler.current_scope(),
                column=validated.column,
                limit=validated.limit,
            )

            if "error" in result:
                return StructuredError(
                    error=ErrorDetail(
                        error_code="DISTINCT_ERROR",
                        error_message=result["error"].get("message", "Unknown error"),
                        retry_eligible=result["error"].get("recoverable", False),
                        suggestion=(
                            "Check the spool_id and column name. "
                            "Use @spooler_list to see available "
                            "spools and their columns."
                        ),
                    ),
                ).to_dict()

            return result

        except RuntimeError as exc:
            logger.error("Spooler not available: %s", exc)
            return StructuredError(
                error=ErrorDetail(
                    error_code="SPOOLER_UNAVAILABLE",
                    error_message=str(exc),
                    retry_eligible=False,
                    suggestion=("The response spooler is not initialised."),
                ),
            ).to_dict()
        except Exception as exc:
            logger.exception("Unexpected error in spooler_distinct: %s", exc)
            return StructuredError(
                error=ErrorDetail(
                    error_code="INTERNAL_ERROR",
                    error_message=f"An unexpected error occurred: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
