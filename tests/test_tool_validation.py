"""Tests for strict tool argument validation.

A silently ignored argument is a correctness hazard for a model-facing
API: the caller believes the constraint was applied and presents the
result as an answer. Unknown arguments must be rejected loudly enough
that the caller can self-correct in one turn.
"""

import pytest
from pydantic import BaseModel, Field

from spindl.tool import BaseTool, ToolInputError


class GetDevices(BaseTool):
    name = "get_devices"
    description = "List devices"
    category = "inventory"

    class InputModel(BaseModel):
        site: str = Field(description="Site code")
        limit: int = Field(default=50, ge=1, le=500)

    async def execute(self, **params):
        validated = self.validate_input(params)
        return {"success": True, "site": validated.site}


class NoInputTool(BaseTool):
    name = "ping"
    description = "Take no arguments"
    category = "diagnostics"

    async def execute(self, **params):
        self.validate_input(params)
        return {"success": True}


class LenientTool(GetDevices):
    name = "lenient"
    reject_unknown_arguments = False


class TestAcceptedArguments:
    def test_lists_input_model_fields(self):
        assert GetDevices().accepted_arguments() == ["limit", "site"]

    def test_is_empty_without_an_input_model(self):
        assert NoInputTool().accepted_arguments() == []


class TestUnknownArguments:
    def test_unknown_argument_raises(self):
        with pytest.raises(ToolInputError) as exc_info:
            GetDevices().validate_input({"site": "syd", "filters": []})
        assert "filters" in str(exc_info.value)

    def test_error_names_rejected_and_accepted_arguments(self):
        with pytest.raises(ToolInputError) as exc_info:
            GetDevices().validate_input({"site": "syd", "filters": [], "sort": "x"})
        payload = exc_info.value.to_dict()
        assert payload["success"] is False
        assert payload["error"]["error_code"] == "INVALID_ARGUMENTS"
        # Rejected keys are reported in a stable order.
        assert "'filters', 'sort'" in payload["error"]["error_message"]
        assert "limit" in payload["error"]["suggestion"]
        assert "site" in payload["error"]["suggestion"]

    def test_error_is_retry_eligible(self):
        with pytest.raises(ToolInputError) as exc_info:
            GetDevices().validate_input({"site": "syd", "nope": 1})
        assert exc_info.value.to_dict()["error"]["retry_eligible"] is True

    def test_tool_without_input_model_rejects_any_argument(self):
        with pytest.raises(ToolInputError) as exc_info:
            NoInputTool().validate_input({"spool_id": "abc"})
        assert "spool_id" in str(exc_info.value)

    def test_opt_out_allows_unknown_arguments(self):
        validated = LenientTool().validate_input({"site": "syd", "filters": []})
        assert validated.site == "syd"

    async def test_execute_surfaces_the_error_through_the_tool(self):
        with pytest.raises(ToolInputError):
            await GetDevices().execute(site="syd", filters=[])


class TestFieldValidation:
    def test_out_of_range_value_raises_tool_input_error(self):
        with pytest.raises(ToolInputError) as exc_info:
            GetDevices().validate_input({"site": "syd", "limit": 9000})
        payload = exc_info.value.to_dict()
        assert payload["error"]["error_code"] == "INVALID_ARGUMENTS"
        assert "limit" in payload["error"]["error_message"]

    def test_missing_required_value_raises_tool_input_error(self):
        with pytest.raises(ToolInputError) as exc_info:
            GetDevices().validate_input({})
        assert "site" in str(exc_info.value)

    def test_valid_arguments_return_the_model(self):
        validated = GetDevices().validate_input({"site": "syd", "limit": 10})
        assert validated.limit == 10

    def test_no_input_model_returns_none(self):
        assert NoInputTool().validate_input({}) is None
