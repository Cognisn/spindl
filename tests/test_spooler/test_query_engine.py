"""Tests for QueryEngine."""

import pytest

from spindl.spooler.query_engine import QueryEngine


class TestQueryEngineList:
    async def test_list_spools(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.list_spools()
        assert result["total_spools"] >= 1
        assert any(s["spool_id"] == spool_id for s in result["spools"])

    async def test_list_empty(self, spooler):
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.list_spools()
        assert result["total_spools"] == 0


class TestQueryEngineQuery:
    async def test_basic_query(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(spool_id=spool_id)
        assert "results" in result
        assert result["pagination"]["total_records"] == 50

    async def test_filter(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(
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
        for row in result["results"]:
            assert row["severity"] == "critical"

    async def test_sort(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(
            spool_id=spool_id,
            sort_by="cvss_score",
            sort_order="desc",
            page_size=50,
        )
        scores = [r["cvss_score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True)

    async def test_pagination(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(spool_id=spool_id, page=2, page_size=5)
        assert result["pagination"]["page"] == 2
        assert result["pagination"]["has_previous"] is True
        assert len(result["results"]) == 5

    async def test_columns(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(spool_id=spool_id, columns=["cve_id", "severity"])
        for row in result["results"]:
            assert set(row.keys()) == {"cve_id", "severity"}

    async def test_search(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(spool_id=spool_id, search="CVE-2024-1010")
        assert result["pagination"]["total_records"] >= 1

    async def test_invalid_spool(self, spooler_with_data):
        spooler, _ = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.query(spool_id="nonexistent")
        assert "error" in result


class TestQueryEngineAggregate:
    async def test_count_by_severity(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.aggregate(
            spool_id=spool_id,
            group_by=["severity"],
            aggregates=[{"function": "count", "column": "*", "alias": "total"}],
        )
        assert result["total_groups"] == 4
        total = sum(r["total"] for r in result["results"])
        assert total == 50

    async def test_avg_score(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.aggregate(
            spool_id=spool_id,
            aggregates=[
                {
                    "function": "avg",
                    "column": "cvss_score",
                    "alias": "avg_score",
                }
            ],
        )
        assert len(result["results"]) == 1
        assert abs(result["results"][0]["avg_score"] - 6.15) < 0.01

    async def test_countdistinct(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.aggregate(
            spool_id=spool_id,
            aggregates=[
                {
                    "function": "countdistinct",
                    "column": "severity",
                    "alias": "unique",
                }
            ],
        )
        assert result["results"][0]["unique"] == 4

    async def test_countdistinct_star_rejected(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.aggregate(
            spool_id=spool_id,
            aggregates=[
                {
                    "function": "countdistinct",
                    "column": "*",
                    "alias": "bad",
                }
            ],
        )
        assert "error" in result

    async def test_pagination(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.aggregate(
            spool_id=spool_id,
            group_by=["severity"],
            aggregates=[{"function": "count", "column": "*", "alias": "total"}],
            page=1,
            page_size=2,
        )
        assert "pagination" in result
        assert result["pagination"]["total_groups"] == 4
        assert result["pagination"]["has_next"] is True
        assert len(result["results"]) == 2


class TestQueryEngineDistinct:
    async def test_distinct_severity(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.get_distinct_values(spool_id=spool_id, column="severity")
        assert result["total_distinct"] == 4
        values = {v["value"] for v in result["distinct_values"]}
        assert values == {"critical", "high", "medium", "low"}

    async def test_invalid_column(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.get_distinct_values(spool_id=spool_id, column="nonexistent")
        assert "error" in result

    async def test_high_limit(self, spooler_with_data):
        spooler, spool_id = spooler_with_data
        engine = QueryEngine(spooler.get_connection(), spooler.config)
        result = engine.get_distinct_values(
            spool_id=spool_id, column="cve_id", limit=500
        )
        assert result["total_distinct"] == 50
