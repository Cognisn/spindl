"""Query spooled data with filtering, sorting, and pagination."""

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class SpoolerQueryTool(BaseTool):
    """Query spooled data with filtering, sorting, and pagination."""

    name = "spooler_query"
    description = "Query spooled data with filtering, sorting, and pagination"
    category = "spooler"

    class InputModel(BaseModel):
        spool_id: str = Field(
            description=(
                "The spool_id from the spooled_data summary returned "
                "by the original tool call"
            ),
        )
        columns: Optional[list[str]] = Field(
            default=None,
            description="Columns to return. Omit for all columns.",
        )
        filters: Optional[list[dict[str, Any]]] = Field(
            default=None,
            description=(
                "Filter conditions. Each dict has: column, operator "
                "(eq/neq/gt/gte/lt/lte/like/not_like/is_null/"
                "is_not_null/in), value"
            ),
        )
        sort_by: Optional[str] = Field(
            default=None,
            description="Column to sort by",
        )
        sort_order: str = Field(
            default="asc",
            description="Sort direction: asc or desc",
        )
        page: int = Field(
            default=1,
            description="Page number (1-indexed)",
            ge=1,
        )
        page_size: Optional[int] = Field(
            default=None,
            description="Records per page (default 20, max 50)",
            ge=1,
            le=50,
        )
        search: Optional[str] = Field(
            default=None,
            description="Free-text search across text columns",
        )
        search_columns: Optional[list[str]] = Field(
            default=None,
            description="Specific columns to search in",
        )

    def __init__(self, spooler: Any) -> None:
        self._spooler = spooler

    def guide(self) -> str:
        return (
            "# @spooler_query\n\n"
            "**Category:** spooler\n"
            "**Description:** Query spooled data with filtering, "
            "sorting, and pagination\n\n"
            "## Parameters\n\n"
            "- **spool_id** (required): The spool_id from the "
            "spooled_data summary in the original tool response\n"
            "- **columns** (optional): List of column names to return\n"
            "- **filters** (optional): List of filter condition dicts\n"
            "- **sort_by** (optional): Column name to sort results by\n"
            "- **sort_order** (optional): 'asc' or 'desc' (default: 'asc')\n"
            "- **page** (optional): Page number, 1-indexed (default: 1)\n"
            "- **page_size** (optional): Records per page, 1-50 "
            "(default: 20)\n"
            "- **search** (optional): Free-text search string\n"
            "- **search_columns** (optional): Columns to search in\n\n"
            "## Filter Operators\n\n"
            "| Operator | Description |\n"
            "|----------|-------------|\n"
            "| eq | Equals |\n"
            "| neq | Not equals |\n"
            "| gt | Greater than |\n"
            "| gte | Greater than or equal |\n"
            "| lt | Less than |\n"
            "| lte | Less than or equal |\n"
            "| like | Pattern match (% wildcard) |\n"
            "| not_like | Negative pattern match |\n"
            "| is_null | Value is null |\n"
            "| is_not_null | Value is not null |\n"
            "| in | Value in list |\n\n"
            "## Examples\n\n"
            "### Browse all records\n"
            '```json\n{"spool_id": "a1b2c3d4e5f6"}\n```\n\n'
            "### Filter by column value\n"
            '```json\n{"spool_id": "SPOOL_ID", '
            '"filters": [{"column": "severity", "operator": "eq", '
            '"value": "critical"}]}\n```\n\n'
            "### Paginate through results\n"
            "Check `pagination.has_next`, then increment page:\n"
            '```json\n{"spool_id": "SPOOL_ID", '
            '"page": 1, "page_size": 50}\n```\n\n'
            "## Related Tools\n\n"
            "- @spooler_list -- see all available spools\n"
            "- @spooler_aggregate -- group-by aggregation\n"
            "- @spooler_distinct -- unique value discovery\n"
        )

    async def execute(self, **params: Any) -> dict[str, Any]:
        try:
            validated = self.InputModel(**params)
            self._spooler.require_initialised()

            result: dict[str, Any] = await self._spooler.backend.query(
                spool_id=validated.spool_id,
                scope=self._spooler.current_scope(),
                columns=validated.columns,
                filters=validated.filters,
                sort_by=validated.sort_by,
                sort_order=validated.sort_order,
                page=validated.page,
                page_size=validated.page_size,
                search=validated.search,
                search_columns=validated.search_columns,
            )

            if "error" in result:
                return StructuredError(
                    error=ErrorDetail(
                        error_code="QUERY_ERROR",
                        error_message=result["error"].get(
                            "message", "Unknown query error"
                        ),
                        retry_eligible=result["error"].get("recoverable", False),
                        suggestion=(
                            "Check the spool_id, column names, and "
                            "filter syntax. Use @spooler_list to see "
                            "available spools and their columns."
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
                        "The response spooler is not initialised. "
                        "This may indicate that no data has been "
                        "spooled yet in this session."
                    ),
                ),
            ).to_dict()
        except Exception as exc:
            logger.error("Unexpected error in spooler_query: %s", exc)
            return StructuredError(
                error=ErrorDetail(
                    error_code="INTERNAL_ERROR",
                    error_message=f"An unexpected error occurred: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
