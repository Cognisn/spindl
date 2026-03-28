"""Response spooler for intercepting large API array responses.

Stores array data in ephemeral SQLite and provides the LLM with
summary metadata and generic query tools to access data on demand.
"""

from spindl.spooler.config import SpoolerConfig
from spindl.spooler.query_engine import QueryEngine
from spindl.spooler.spooler import ResponseSpooler

__all__ = [
    "SpoolerConfig",
    "QueryEngine",
    "ResponseSpooler",
]
