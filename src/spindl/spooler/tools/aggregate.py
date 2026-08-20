"""Aggregate spooled data with grouping and summary functions."""

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class SpoolerAggregateTool(BaseTool):
    """Aggregate spooled data with grouping and summary functions."""

    name = "spooler_aggregate"
    description = (
        "Aggregate spooled data with grouping and summary functions"
    )
    category = "spooler"

    class InputModel(BaseModel):
        spool_id: str = Field(
            description=(
                "The spool_id from the spooled_data summary returned "
                "by the original tool call"
            ),
        )
        group_by: Optional[list[str]] = Field(
            default=None,
            description="Columns to group by",
        )
        aggregates: Optional[list[dict]] = Field(
            default=None,
            description=(
                "Aggregation operations. Each dict has: function "
                "(count/countdistinct/sum/avg/min/max), column, alias"
            ),
        )
        filters: Optional[list[dict]] = Field(
            default=None,
            description="Optional filters before aggregation",
        )
        sort_by: Optional[str] = Field(
            default=None,
            description="Column or alias to sort results by",
        )
        sort_order: str = Field(
            default="desc",
            description="Sort direction: asc or desc",
        )
        limit: int = Field(
            default=50,
            description="Maximum number of groups to return",
            ge=1,
            le=500,
        )
        page: int = Field(
            default=1,
            description="Page number (1-indexed) for paginated results",
            ge=1,
        )
        page_size: Optional[int] = Field(
            default=None,
            description=(
                "Groups per page. Enables paginated results with "
                "has_next/has_previous metadata (max 500)"
            ),
            ge=1,
            le=500,
        )

    def __init__(self, spooler: Any) -> None:
        self._spooler = spooler

    def guide(self) -> str:
        return (
            "# @spooler_aggregate\n\n"
            "**Category:** spooler\n"
            "**Description:** Aggregate spooled data with grouping "
            "and summary functions\n\n"
            "## Parameters\n\n"
            "- **spool_id** (required): The spool_id from the "
            "spooled_data summary\n"
            "- **group_by** (optional): Columns to group by\n"
            "- **aggregates** (optional): List of aggregation dicts "
            "with function, column, alias\n"
            "- **filters** (optional): Pre-aggregation filters\n"
            "- **sort_by** (optional): Column or alias to sort by\n"
            "- **sort_order** (optional): 'asc' or 'desc' "
            "(default: 'desc')\n"
            "- **limit** (optional): Max groups, 1-500 (default: 50)\n"
            "- **page** (optional): Page number (default: 1)\n"
            "- **page_size** (optional): Groups per page, 1-500\n\n"
            "## Aggregate Functions\n\n"
            "| Function | Description | Column |\n"
            "|----------|-------------|--------|\n"
            "| count | Count records | Use '*' |\n"
            "| countdistinct | Count unique values | Column name |\n"
            "| sum | Sum numeric values | Numeric column |\n"
            "| avg | Average numeric values | Numeric column |\n"
            "| min | Minimum value | Any column |\n"
            "| max | Maximum value | Any column |\n\n"
            "## IMPORTANT: count vs countdistinct\n\n"
            "- **count** counts rows. If one device has 5 vulnerability "
            "records, `count(*)` returns 5.\n"
            "- **countdistinct** counts unique values. "
            "`countdistinct(DeviceId)` returns 1.\n\n"
            "## Examples\n\n"
            "### Count by category\n"
            '```json\n{"spool_id": "SPOOL_ID", '
            '"group_by": ["severity"], '
            '"aggregates": [{"function": "count", "column": "*", '
            '"alias": "total"}], '
            '"sort_by": "total", "sort_order": "desc"}\n```\n\n'
            "## Related Tools\n\n"
            "- @spooler_list -- see all available spools\n"
            "- @spooler_query -- filter and paginate records\n"
            "- @spooler_distinct -- unique value discovery\n"
        )

    async def execute(self, **params: Any) -> dict:
        try:
            validated = self.InputModel(**params)
            self._spooler.require_initialised()

            result = self._spooler.backend.aggregate(
                spool_id=validated.spool_id,
                scope=self._spooler.current_scope(),
                group_by=validated.group_by,
                aggregates=validated.aggregates,
                filters=validated.filters,
                sort_by=validated.sort_by,
                sort_order=validated.sort_order,
                limit=validated.limit,
                page=validated.page,
                page_size=validated.page_size,
            )

            if "error" in result:
                return StructuredError(
                    error=ErrorDetail(
                        error_code="AGGREGATION_ERROR",
                        error_message=result["error"].get(
                            "message", "Unknown aggregation error"
                        ),
                        retry_eligible=result["error"].get(
                            "recoverable", False
                        ),
                        suggestion=(
                            "Check the spool_id, column names, and "
                            "aggregate functions. Use @spooler_list "
                            "to see available spools."
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
                    suggestion=(
                        "The response spooler is not initialised."
                    ),
                ),
            ).to_dict()
        except Exception as exc:
            logger.error(
                "Unexpected error in spooler_aggregate: %s", exc
            )
            return StructuredError(
                error=ErrorDetail(
                    error_code="INTERNAL_ERROR",
                    error_message=f"An unexpected error occurred: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
