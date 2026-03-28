"""Tests for BaseTool."""

import pytest
from pydantic import BaseModel, Field

from spindl.tool import BaseTool


class TestBaseTool:
    def test_input_schema_from_model(self, sample_tool):
        schema = sample_tool.input_schema
        assert schema["type"] == "object"
        assert "limit" in schema["properties"]

    def test_input_schema_no_model(self):
        class NoModel(BaseTool):
            name = "no_model"
            description = "Test"
            category = "test"

        tool = NoModel()
        schema = tool.input_schema
        assert schema == {"type": "object", "properties": {}}

    def test_default_guide(self):
        """Test the auto-generated guide from InputModel fields."""

        class DefaultGuide(BaseTool):
            name = "my_tool"
            description = "A test tool"
            category = "test"

            class InputModel(BaseModel):
                limit: int = Field(default=50, description="Max items")

        tool = DefaultGuide()
        guide = tool.guide()
        assert "my_tool" in guide
        assert "limit" in guide
        assert "optional" in guide

    def test_custom_guide(self, sample_tool):
        """sample_tool overrides guide() with @placeholder syntax."""
        guide = sample_tool.guide()
        assert "@spooler_query" in guide

    def test_execute_not_implemented(self):
        class Incomplete(BaseTool):
            name = "incomplete"
            description = "Test"
            category = "test"

        tool = Incomplete()
        with pytest.raises(NotImplementedError, match="incomplete"):
            import asyncio

            asyncio.run(tool.execute())

    def test_default_attributes(self):
        tool = BaseTool()
        assert tool.is_write_operation is False
        assert tool.spooler_array_paths is None
        assert tool.spooler_auto_detect is False
        assert tool.InputModel is None
