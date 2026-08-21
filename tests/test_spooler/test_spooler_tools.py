"""Tests for spooler tools."""

import pytest

from spindl.spooler.config import SpoolerConfig
from spindl.spooler.spooler import ResponseSpooler
from spindl.spooler.tools.aggregate import SpoolerAggregateTool
from spindl.spooler.tools.distinct import SpoolerDistinctTool
from spindl.spooler.tools.list_spools import SpoolerListSpoolsTool
from spindl.spooler.tools.query import SpoolerQueryTool


class InMemoryBackend:
    """Stand-in backend; the spooler is never initialised in these tests."""

    async def initialise(self) -> None: ...

    async def cleanup(self) -> None: ...


class TestSpoolerToolMetadata:
    def test_list_spools_metadata(self):
        assert SpoolerListSpoolsTool.name == "spooler_list"
        assert SpoolerListSpoolsTool.category == "spooler"

    def test_query_metadata(self):
        assert SpoolerQueryTool.name == "spooler_query"
        assert SpoolerQueryTool.category == "spooler"

    def test_aggregate_metadata(self):
        assert SpoolerAggregateTool.name == "spooler_aggregate"
        assert SpoolerAggregateTool.category == "spooler"

    def test_distinct_metadata(self):
        assert SpoolerDistinctTool.name == "spooler_distinct"
        assert SpoolerDistinctTool.category == "spooler"


class TestSpoolerToolGuides:
    def test_list_spools_guide(self, spooler):
        tool = SpoolerListSpoolsTool(spooler=spooler)
        guide = tool.guide()
        assert "@spooler_list" in guide
        assert "@spooler_query" in guide

    def test_query_guide(self, spooler):
        tool = SpoolerQueryTool(spooler=spooler)
        guide = tool.guide()
        assert "@spooler_query" in guide
        assert "@spooler_list" in guide

    def test_aggregate_guide(self, spooler):
        tool = SpoolerAggregateTool(spooler=spooler)
        guide = tool.guide()
        assert "@spooler_aggregate" in guide

    def test_distinct_guide(self, spooler):
        tool = SpoolerDistinctTool(spooler=spooler)
        guide = tool.guide()
        assert "@spooler_distinct" in guide


class TestSpoolerListSpools:
    @pytest.mark.asyncio
    async def test_list_with_data(self, spooler_with_data):
        spooler, _ = spooler_with_data
        tool = SpoolerListSpoolsTool(spooler=spooler)
        result = await tool.execute()
        assert result["success"] is True
        assert result["data"]["total_spools"] >= 1

    @pytest.mark.asyncio
    async def test_list_empty(self, spooler):
        tool = SpoolerListSpoolsTool(spooler=spooler)
        result = await tool.execute()
        assert result["success"] is True
        assert result["data"]["total_spools"] == 0

    @pytest.mark.asyncio
    async def test_unavailable(self):
        mock = ResponseSpooler(SpoolerConfig(backend=InMemoryBackend()))
        tool = SpoolerListSpoolsTool(spooler=mock)
        result = await tool.execute()
        assert result["success"] is False
        assert result["error"]["error_code"] == "SPOOLER_UNAVAILABLE"


class TestSpoolerQuery:
    @pytest.mark.asyncio
    async def test_basic_query(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        tool = SpoolerQueryTool(spooler=spooler)
        result = await tool.execute(spool_id=spool_id)
        assert "results" in result
        assert result["pagination"]["total_records"] == 50

    @pytest.mark.asyncio
    async def test_filter(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        tool = SpoolerQueryTool(spooler=spooler)
        result = await tool.execute(
            spool_id=spool_id,
            filters=[
                {
                    "column": "severity",
                    "operator": "eq",
                    "value": "critical",
                }
            ],
        )
        assert result["pagination"]["total_records"] == 13

    @pytest.mark.asyncio
    async def test_invalid_spool(self, spooler_with_data):
        spooler, _ = spooler_with_data
        tool = SpoolerQueryTool(spooler=spooler)
        result = await tool.execute(spool_id="nonexistent")
        assert result["success"] is False
        assert result["error"]["error_code"] == "QUERY_ERROR"

    @pytest.mark.asyncio
    async def test_unavailable(self):
        mock = ResponseSpooler(SpoolerConfig(backend=InMemoryBackend()))
        tool = SpoolerQueryTool(spooler=mock)
        result = await tool.execute(spool_id="any")
        assert result["success"] is False
        assert result["error"]["error_code"] == "SPOOLER_UNAVAILABLE"


class TestSpoolerAggregate:
    @pytest.mark.asyncio
    async def test_count_by_severity(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        tool = SpoolerAggregateTool(spooler=spooler)
        result = await tool.execute(
            spool_id=spool_id,
            group_by=["severity"],
            aggregates=[{"function": "count", "column": "*", "alias": "total"}],
        )
        assert result["total_groups"] == 4

    @pytest.mark.asyncio
    async def test_invalid_spool(self, spooler_with_data):
        spooler, _ = spooler_with_data
        tool = SpoolerAggregateTool(spooler=spooler)
        result = await tool.execute(spool_id="nonexistent")
        assert result["success"] is False
        assert result["error"]["error_code"] == "AGGREGATION_ERROR"

    @pytest.mark.asyncio
    async def test_unavailable(self):
        mock = ResponseSpooler(SpoolerConfig(backend=InMemoryBackend()))
        tool = SpoolerAggregateTool(spooler=mock)
        result = await tool.execute(spool_id="any")
        assert result["success"] is False
        assert result["error"]["error_code"] == "SPOOLER_UNAVAILABLE"


class TestSpoolerDistinct:
    @pytest.mark.asyncio
    async def test_distinct(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        tool = SpoolerDistinctTool(spooler=spooler)
        result = await tool.execute(spool_id=spool_id, column="severity")
        assert result["total_distinct"] == 4

    @pytest.mark.asyncio
    async def test_invalid_column(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        tool = SpoolerDistinctTool(spooler=spooler)
        result = await tool.execute(spool_id=spool_id, column="nonexistent")
        assert result["success"] is False
        assert result["error"]["error_code"] == "DISTINCT_ERROR"

    @pytest.mark.asyncio
    async def test_unavailable(self):
        mock = ResponseSpooler(SpoolerConfig(backend=InMemoryBackend()))
        tool = SpoolerDistinctTool(spooler=mock)
        result = await tool.execute(spool_id="any", column="severity")
        assert result["success"] is False
        assert result["error"]["error_code"] == "SPOOLER_UNAVAILABLE"
