"""Configuration for the response spooler.

All thresholds and limits are configurable via environment variables
or direct instantiation, with sensible defaults for container deployment.
"""

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SpoolerConfig:
    """Configuration for the response spooler.

    Attributes:
        db_path: Path to the SQLite database file. Defaults to the
                 system temporary directory for ephemeral storage.
        max_inline_tokens: Estimated token count threshold above which
                          array data is spooled to SQLite rather than
                          returned inline. Default 2000 (~8000 chars).
        max_inline_items: Maximum number of array items to return inline
                         before spooling. Default 10.
        default_page_size: Default number of records returned per query
                          page. Default 20.
        max_page_size: Hard ceiling on page size to prevent context
                      window overload. Default 50.
        summary_sample_size: Number of records to include in the summary
                            sample sent back to the LLM. Default 3.
        chars_per_token: Rough character-to-token ratio for size
                        estimation. Default 4.
        db_cleanup_on_exit: Whether to delete the database file when
                           the spooler is closed. Default True for
                           container deployments.
    """

    db_path: str = field(
        default_factory=lambda: os.environ.get(
            "SPOOLER_DB_PATH",
            os.path.join(tempfile.gettempdir(), "mcp_spooler.db"),
        )
    )
    max_inline_tokens: int = field(
        default_factory=lambda: int(
            os.environ.get("SPOOLER_MAX_INLINE_TOKENS", "2000")
        )
    )
    max_inline_items: int = field(
        default_factory=lambda: int(
            os.environ.get("SPOOLER_MAX_INLINE_ITEMS", "10")
        )
    )
    default_page_size: int = field(
        default_factory=lambda: int(
            os.environ.get("SPOOLER_DEFAULT_PAGE_SIZE", "20")
        )
    )
    max_page_size: int = field(
        default_factory=lambda: int(
            os.environ.get("SPOOLER_MAX_PAGE_SIZE", "50")
        )
    )
    summary_sample_size: int = field(
        default_factory=lambda: int(
            os.environ.get("SPOOLER_SUMMARY_SAMPLE_SIZE", "3")
        )
    )
    chars_per_token: int = 4
    db_cleanup_on_exit: bool = field(
        default_factory=lambda: os.environ.get(
            "SPOOLER_CLEANUP_ON_EXIT", "true"
        ).lower() == "true"
    )

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate based on character count."""
        return len(text) // self.chars_per_token

    def validate(self) -> None:
        """Validate configuration values."""
        if self.max_page_size < 1:
            raise ValueError("max_page_size must be at least 1")
        if self.default_page_size > self.max_page_size:
            raise ValueError(
                "default_page_size cannot exceed max_page_size"
            )
        if self.max_inline_items < 0:
            raise ValueError("max_inline_items must be non-negative")

        # Ensure the database directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
