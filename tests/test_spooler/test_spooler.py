"""Tests for ResponseSpooler."""

import pytest

from spindl.spooler.spooler import ResponseSpooler


class TestResponseSpooler:
    def test_not_initialised_raises(self, spooler_config):
        s = ResponseSpooler(spooler_config)
        with pytest.raises(RuntimeError, match="not initialised"):
            s.process_response(
                response={"data": []}, source_tool="test"
            )

    @pytest.mark.asyncio
    async def test_initialise(self, spooler_config):
        s = ResponseSpooler(spooler_config)
        await s.initialise()
        assert s._initialised is True
        await s.cleanup()

    def test_small_array_inline(self, spooler):
        result = spooler.process_response(
            response={"items": [{"id": 1}, {"id": 2}]},
            source_tool="test",
            array_paths=["items"],
        )
        assert "spooled_data" not in result
        assert result.get("items") == [{"id": 1}, {"id": 2}]

    def test_large_array_spooled(self, spooler):
        items = [{"id": i, "name": f"item-{i}"} for i in range(50)]
        result = spooler.process_response(
            response={"items": items},
            source_tool="test",
            array_paths=["items"],
        )
        assert "spooled_data" in result
        assert result["spooled_data"][0]["total_records"] == 50

    def test_auto_detect_arrays(self, spooler):
        items = [{"id": i, "val": f"v{i}"} for i in range(50)]
        result = spooler.process_response(
            response={"data": items, "meta": "info"},
            source_tool="test",
        )
        assert "spooled_data" in result

    def test_list_response_wrapped(self, spooler):
        items = [{"id": i} for i in range(50)]
        result = spooler.process_response(
            response=items, source_tool="test"
        )
        assert "spooled_data" in result

    def test_spool_summary_has_sample(self, spooler):
        items = [{"id": i, "name": f"item-{i}"} for i in range(50)]
        result = spooler.process_response(
            response={"items": items},
            source_tool="test",
            array_paths=["items"],
        )
        spool = result["spooled_data"][0]
        assert "sample_records" in spool
        assert len(spool["sample_records"]) == 3

    def test_spool_summary_has_columns(self, spooler):
        items = [{"id": i, "name": f"item-{i}"} for i in range(50)]
        result = spooler.process_response(
            response={"items": items},
            source_tool="test",
            array_paths=["items"],
        )
        spool = result["spooled_data"][0]
        assert "id" in spool["columns"]
        assert "name" in spool["columns"]

    def test_guidance_uses_placeholders(self, spooler):
        items = [{"id": i} for i in range(50)]
        result = spooler.process_response(
            response={"items": items},
            source_tool="test",
            array_paths=["items"],
        )
        instructions = result["_spooler_meta"]["instructions"]
        assert "@spooler_query" in instructions
        assert "@spooler_aggregate" in instructions

    def test_get_connection(self, spooler):
        conn = spooler.get_connection()
        assert conn is not None

    def test_get_connection_not_initialised(self, spooler_config):
        s = ResponseSpooler(spooler_config)
        with pytest.raises(RuntimeError):
            s.get_connection()
