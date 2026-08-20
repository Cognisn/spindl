"""Shared test fixtures for spindl."""

import pytest
from pydantic import BaseModel, Field

from spindl.prefix import PrefixResolver
from spindl.registry import ToolRegistry
from spindl.spooler.config import SpoolerConfig
from spindl.spooler.spooler import ResponseSpooler
from spindl.tool import BaseTool


@pytest.fixture
def prefix_resolver():
    """A PrefixResolver with server prefix 'test'."""
    return PrefixResolver("test")


@pytest.fixture
def registry(prefix_resolver):
    """A ToolRegistry backed by the test prefix resolver."""
    return ToolRegistry(prefix_resolver)


@pytest.fixture
def sample_tool():
    """A sample tool for testing."""

    class GetDevices(BaseTool):
        name = "get_devices"
        description = "List devices"
        category = "inventory"

        class InputModel(BaseModel):
            limit: int = Field(default=50, ge=1, le=500)

        def guide(self):
            return "Use @get_devices. Query with @spooler_query."

        async def execute(self, **params):
            return {"success": True, "data": []}

    return GetDevices()


@pytest.fixture
def spooler_config(tmp_path):
    """A SpoolerConfig using a temp directory."""
    return SpoolerConfig(
        db_path=str(tmp_path / "test_spooler.db"),
        max_inline_tokens=100,
        max_inline_items=5,
        db_cleanup_on_exit=False,
    )


@pytest.fixture
async def spooler(spooler_config):
    """An initialised ResponseSpooler with temp database."""
    s = ResponseSpooler(spooler_config)
    s.initialise()
    yield s
    s.cleanup()


@pytest.fixture
async def spooler_with_data(spooler):
    """A spooler with 50 vulnerability records loaded."""
    vulns = [
        {
            "cve_id": f"CVE-2024-{1000 + i}",
            "severity": ["critical", "high", "medium", "low"][i % 4],
            "cvss_score": [9.8, 7.3, 4.8, 2.3][i % 4],
            "title": f"Test vulnerability {i}",
            "status": "open" if i % 3 != 0 else "resolved",
            "vendor": ["Microsoft", "Apache", "Linux", "Oracle"][i % 4],
        }
        for i in range(50)
    ]
    result = await spooler.process_response(
        response={"scan_id": "test-scan-001", "vulnerabilities": vulns},
        source_tool="test_tool",
        array_paths=["vulnerabilities"],
    )
    spool_id = result["spooled_data"][0]["spool_id"]
    return spooler, spool_id
