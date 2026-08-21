"""Metadata envelope for all tool responses."""

from typing import Any

from pydantic import BaseModel


class ResponseMetadata(BaseModel):
    """Metadata about the response result set."""

    total_results: int
    returned_results: int
    truncated: bool = False
    guidance: str | None = None


class ResponseEnvelope(BaseModel):
    """Standard response wrapper for all tool outputs.

    Provides a consistent structure with success status,
    data payload, and metadata.
    """

    success: bool = True
    platform: str = "spindl"
    data: Any = None
    metadata: ResponseMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the envelope to a dictionary for MCP response."""
        return self.model_dump(exclude_none=True)
