"""Tests for the pluggable SpoolBackend protocol."""

import json
from typing import Any, Optional

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from spindl.spooler.backend import SpoolBackend, SQLiteSpoolBackend
from spindl.spooler.config import SpoolerConfig
from spindl.spooler.spooler import ResponseSpooler
from spindl.spooler.tools.list_spools import SpoolerListSpoolsTool
from spindl.spooler.tools.query import SpoolerQueryTool

ROWS = [{"id": i, "severity": "high" if i % 2 else "low"} for i in range(30)]


class InMemoryBackend:
    """Minimal storage-agnostic backend used to prove the tools delegate."""

    def __init__(self) -> None:
        self.spools: dict[str, dict[str, Any]] = {}
        self.initialised = False

    async def initialise(self) -> None:
        self.initialised = True

    async def cleanup(self) -> None:
        self.initialised = False

    async def create_spool(
        self,
        *,
        spool_id: str,
        source_tool: str,
        array_path: str,
        columns: list[str],
        column_types: dict[str, str],
        rows: list[tuple],
        description: Optional[str] = None,
        scope: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> dict:
        records = [dict(zip(columns, r)) for r in rows]
        self.spools[spool_id] = {
            "source_tool": source_tool,
            "array_path": array_path,
            "columns": columns,
            "records": records,
            "scope": scope,
            "ttl": ttl,
        }
        return {
            "stats": {
                "numeric_columns": [],
                "min_values": {},
                "max_values": {},
                "distinct_counts": {},
            },
            "sample": records[:3],
        }

    async def list_spools(self, *, scope: Optional[str] = None) -> dict:
        spools = [
            {"spool_id": sid, "total_records": len(s["records"])}
            for sid, s in self.spools.items()
        ]
        return {"total_spools": len(spools), "spools": spools}

    async def query(
        self, spool_id: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict:
        spool = self.spools[spool_id]
        return {"spool_id": spool_id, "records": spool["records"], "memory": True}

    async def aggregate(
        self, spool_id: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict:
        return {"spool_id": spool_id, "groups": []}

    async def distinct(
        self, spool_id: str, column: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict:
        return {"values": sorted({r[column] for r in self.spools[spool_id]["records"]})}

    async def delete_spool(self, spool_id: str, *, scope: Optional[str] = None) -> bool:
        return self.spools.pop(spool_id, None) is not None


@pytest.fixture
def sqlite_config(tmp_path):
    return SpoolerConfig(
        db_path=str(tmp_path / "spool.db"),
        max_inline_items=5,
        db_cleanup_on_exit=True,
    )


async def spool(spooler: ResponseSpooler, **kwargs) -> str:
    result = await spooler.process_response(
        {"devices": ROWS}, source_tool="get_devices", array_paths=["devices"], **kwargs
    )
    return result["spooled_data"][0]["spool_id"]


class TestSyncConveniences:
    def test_sync_initialise_with_async_backend_outside_loop(self):
        backend = InMemoryBackend()
        spooler = ResponseSpooler(SpoolerConfig(backend=backend))
        spooler.initialise()
        assert backend.initialised
        spooler.cleanup()
        assert not backend.initialised

    async def test_sync_initialise_with_async_backend_inside_loop_raises(self):
        spooler = ResponseSpooler(SpoolerConfig(backend=InMemoryBackend()))
        with pytest.raises(RuntimeError, match="initialise_async"):
            spooler.initialise()


class TestDefaultBackend:
    def test_sqlite_backend_is_default(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        assert isinstance(spooler.backend, SQLiteSpoolBackend)

    def test_sqlite_backend_satisfies_protocol(self, sqlite_config):
        assert isinstance(SQLiteSpoolBackend(sqlite_config), SpoolBackend)


class TestInjectedBackend:
    async def test_spooler_initialises_and_writes_to_injected_backend(self):
        backend = InMemoryBackend()
        spooler = ResponseSpooler(SpoolerConfig(backend=backend, max_inline_items=5))
        await spooler.initialise_async()
        assert backend.initialised
        spool_id = await spool(spooler)
        assert spool_id in backend.spools
        assert len(backend.spools[spool_id]["records"]) == 30

    async def test_query_tool_delegates_to_injected_backend(self):
        backend = InMemoryBackend()
        spooler = ResponseSpooler(SpoolerConfig(backend=backend, max_inline_items=5))
        await spooler.initialise_async()
        spool_id = await spool(spooler)
        result = await SpoolerQueryTool(spooler=spooler).execute(spool_id=spool_id)
        assert result["memory"] is True
        assert len(result["records"]) == 30

    async def test_list_tool_delegates_to_injected_backend(self):
        backend = InMemoryBackend()
        spooler = ResponseSpooler(SpoolerConfig(backend=backend, max_inline_items=5))
        await spooler.initialise_async()
        await spool(spooler)
        result = await SpoolerListSpoolsTool(spooler=spooler).execute()
        assert result["data"]["total_spools"] == 1


class TestScope:
    async def test_scoped_spool_hidden_from_other_scope(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        spool_id = await spool(spooler, scope="tenant-a")

        backend = spooler.backend
        assert (await backend.list_spools(scope="tenant-b"))["total_spools"] == 0
        assert (await backend.list_spools(scope="tenant-a"))["total_spools"] == 1
        assert "error" in (await backend.query(spool_id, scope="tenant-b"))
        assert "error" not in (await backend.query(spool_id, scope="tenant-a"))

    async def test_unscoped_read_sees_all_spools(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        await spool(spooler, scope="tenant-a")
        await spool(spooler)
        assert (await spooler.backend.list_spools())["total_spools"] == 2

    async def test_scope_is_taken_from_authenticated_identity(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        user = AuthenticatedUser(
            AccessToken(token="t", client_id="c", scopes=["read"], subject="user-9")
        )
        token = auth_context_var.set(user)
        try:
            spool_id = await spool(spooler)
            assert spooler.current_scope() == "user-9"
        finally:
            auth_context_var.reset(token)
        assert "error" in (await spooler.backend.query(spool_id, scope="someone-else"))
        assert "error" not in (await spooler.backend.query(spool_id, scope="user-9"))


class TestExpiry:
    async def test_expired_spool_is_not_listed_or_queryable(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        live = await spool(spooler, ttl=3600)
        dead = await spool(spooler, ttl=-1)
        listed = {
            s["spool_id"] for s in (await spooler.backend.list_spools())["spools"]
        }
        assert live in listed
        assert dead not in listed
        assert "error" in (await spooler.backend.query(dead))

    async def test_default_ttl_from_config(self, tmp_path):
        cfg = SpoolerConfig(
            db_path=str(tmp_path / "s.db"), max_inline_items=5, default_ttl_seconds=-1
        )
        spooler = ResponseSpooler(cfg)
        spooler.initialise()
        spool_id = await spool(spooler)
        assert "error" in (await spooler.backend.query(spool_id))


class TestDelete:
    async def test_delete_spool_removes_registry_and_data(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        spool_id = await spool(spooler)
        assert (await spooler.backend.delete_spool(spool_id)) is True
        assert (await spooler.backend.delete_spool(spool_id)) is False
        assert (await spooler.backend.list_spools())["total_spools"] == 0
        tables = {
            r[0]
            for r in spooler.get_connection().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert f"spool_{spool_id}" not in tables

    async def test_delete_respects_scope(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        spool_id = await spool(spooler, scope="tenant-a")
        assert (await spooler.backend.delete_spool(spool_id, scope="tenant-b")) is False
        assert (await spooler.backend.delete_spool(spool_id, scope="tenant-a")) is True


class TestEnvelopeUnchanged:
    async def test_summary_response_shape_is_preserved(self, sqlite_config):
        spooler = ResponseSpooler(sqlite_config)
        spooler.initialise()
        result = await spooler.process_response(
            {"devices": ROWS}, source_tool="get_devices", array_paths=["devices"]
        )
        entry = result["spooled_data"][0]
        for key in ("spool_id", "total_records", "sample_records", "query_hint"):
            assert key in entry, key
        assert "_spooler_meta" in result
        json.dumps(result)


class TestSpoolIdUniqueness:
    def test_ids_are_unique_when_clock_does_not_advance(
        self, sqlite_config, monkeypatch
    ):
        import spindl.spooler.spooler as spooler_module

        monkeypatch.setattr(
            spooler_module.time, "time_ns", lambda: 1_700_000_000_000_000_000
        )
        spooler = ResponseSpooler(sqlite_config)
        ids = {spooler._generate_spool_id("get_devices", "devices") for _ in range(200)}
        assert len(ids) == 200
