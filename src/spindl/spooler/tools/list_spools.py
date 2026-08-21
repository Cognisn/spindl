"""List all available spooled data sets."""

import logging
from typing import Any

from spindl.responses import ResponseEnvelope, ResponseMetadata
from spindl.responses.errors import ErrorDetail, StructuredError
from spindl.tool import BaseTool

logger = logging.getLogger(__name__)


class SpoolerListSpoolsTool(BaseTool):
    """List all available spooled data sets with their metadata."""

    name = "spooler_list"
    description = "List all available spooled data sets with their metadata"
    category = "spooler"

    def __init__(self, spooler: Any) -> None:
        self._spooler = spooler

    def guide(self) -> str:
        return (
            "# @spooler_list\n\n"
            "**Category:** spooler\n"
            "**Description:** List all available spooled data sets "
            "with their metadata\n\n"
            "## Parameters\n\n"
            "*No parameters required.*\n\n"
            "## What is Spooled Data?\n\n"
            "When a tool returns a large array of results (e.g. hundreds "
            "of vulnerabilities or devices), the response spooler "
            "automatically stores the array data in an efficient "
            "queryable format rather than returning it all inline.\n\n"
            "The original tool response replaces the large array with "
            "a **spooled_data** summary containing:\n"
            "- **spool_id** -- identifier for the spooler query tools\n"
            "- **total_records** -- how many records were stored\n"
            "- **columns** -- available column names\n"
            "- **sample_records** -- first few records as a preview\n"
            "- **query_hint** -- instructions for querying the data\n\n"
            "You then pass the spool_id to @spooler_query, "
            "@spooler_aggregate, or @spooler_distinct to work with "
            "the full data set.\n\n"
            "## Typical Workflow\n\n"
            "1. Call a data tool -- the response includes `spooled_data` "
            "with a spool_id\n"
            "2. Use @spooler_query to filter/sort/paginate\n"
            "3. Use @spooler_aggregate for counts and grouping\n"
            "4. Use @spooler_distinct to explore column values\n"
            "5. If you lose track of spool_ids, call @spooler_list "
            "to see all available spools\n"
        )

    async def execute(self, **params: Any) -> dict[str, Any]:
        try:
            self._spooler.require_initialised()
            result = await self._spooler.backend.list_spools(
                scope=self._spooler.current_scope()
            )

            return ResponseEnvelope(
                success=True,
                data=result,
                metadata=ResponseMetadata(
                    total_results=result.get("total_spools", 0),
                    returned_results=result.get("total_spools", 0),
                    truncated=False,
                ),
            ).to_dict()

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
            logger.exception("Unexpected error in spooler_list: %s", exc)
            return StructuredError(
                error=ErrorDetail(
                    error_code="INTERNAL_ERROR",
                    error_message=f"An unexpected error occurred: {exc}",
                    retry_eligible=True,
                ),
            ).to_dict()
