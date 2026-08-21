"""Structured error response builder."""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Detailed error information."""

    error_code: str
    error_message: str
    retry_eligible: bool = False
    suggestion: str | None = None


class StructuredError(BaseModel):
    """Structured error response for consistent LLM-facing error handling.

    Provides a uniform error format with actionable suggestions
    for recovery.
    """

    success: bool = False
    platform: str = "spindl"
    error: ErrorDetail

    def to_dict(self) -> dict[str, Any]:
        """Convert the error to a dictionary for MCP response."""
        return self.model_dump(exclude_none=True)
