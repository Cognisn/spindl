"""Tests for response types."""

from spindl.responses import (
    ResponseEnvelope,
    ResponseMetadata,
    ErrorDetail,
    StructuredError,
)


class TestResponseEnvelope:
    def test_to_dict(self):
        env = ResponseEnvelope(
            success=True,
            data={"items": [1, 2, 3]},
            metadata=ResponseMetadata(
                total_results=3,
                returned_results=3,
            ),
        )
        d = env.to_dict()
        assert d["success"] is True
        assert d["data"]["items"] == [1, 2, 3]
        assert d["metadata"]["total_results"] == 3

    def test_excludes_none(self):
        env = ResponseEnvelope(success=True, data=None)
        d = env.to_dict()
        assert "data" not in d
        assert "metadata" not in d

    def test_default_platform(self):
        env = ResponseEnvelope(success=True)
        assert env.platform == "spindl"


class TestStructuredError:
    def test_to_dict(self):
        err = StructuredError(
            error=ErrorDetail(
                error_code="TEST_ERROR",
                error_message="Something went wrong",
                suggestion="Try again",
            ),
        )
        d = err.to_dict()
        assert d["success"] is False
        assert d["error"]["error_code"] == "TEST_ERROR"
        assert d["error"]["suggestion"] == "Try again"

    def test_default_values(self):
        err = StructuredError(
            error=ErrorDetail(
                error_code="ERR",
                error_message="msg",
            ),
        )
        d = err.to_dict()
        assert d["error"]["retry_eligible"] is False
        assert d["platform"] == "spindl"
