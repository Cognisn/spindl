"""Pluggable storage for spooled responses.

``SpoolBackend`` is the seam between the spooler and its storage. The
``ResponseSpooler`` flattens arrays and builds the LLM-facing summary; the
backend stores rows and answers the four query tools. ``SQLiteSpoolBackend``
is the default and the only backend shipped with spindl; adopters running
several replicas can inject a shared backend through
``SpoolerConfig(backend=...)``.

Every read operation accepts an optional ``scope``. A spool created with a
scope is only visible to reads carrying the same scope. Reads without a
scope see everything, which is the behaviour when authentication is not
enabled. Spools may also carry a ``ttl`` in seconds after which they are
treated as absent.

The protocol is asynchronous because spindl's tool dispatch runs on the MCP
SDK's event loop: a network backend (for example Postgres) must not block
that loop, so it should use a native async driver or wrap a blocking one in
``asyncio.to_thread``. The SQLite backend exposes thin ``async def`` methods
over its local, sub-millisecond calls.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from spindl.spooler.config import SpoolerConfig
    from spindl.spooler.query_engine import QueryEngine

logger = logging.getLogger(__name__)


@runtime_checkable
class SpoolBackend(Protocol):
    """Storage contract for spooled array data."""

    async def initialise(self) -> None:
        """Open connections and create any schema. Idempotent."""

    async def cleanup(self) -> None:
        """Close connections and release resources."""

    async def create_spool(
        self,
        *,
        spool_id: str,
        source_tool: str,
        array_path: str,
        columns: list[str],
        column_types: dict[str, str],
        rows: list[tuple[Any, ...]],
        description: Optional[str] = None,
        scope: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> dict[str, Any]:
        """Store flattened rows under ``spool_id``.

        Returns a dict with ``stats`` (``numeric_columns``, ``min_values``,
        ``max_values``, ``distinct_counts``) and ``sample`` (a short list of
        records) for the summary response.
        """

    async def list_spools(  # NOSONAR(python:S7503) protocol requires a coroutine
        self, *, scope: Optional[str] = None
    ) -> dict[str, Any]:
        """Return ``{"total_spools": int, "spools": [...]}`` visible to ``scope``."""

    async def query(
        self,
        spool_id: str,
        *,
        columns: Optional[list[str]] = None,
        filters: Optional[dict[str, Any]] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc",
        page: int = 1,
        page_size: Optional[int] = None,
        search: Optional[str] = None,
        search_columns: Optional[list[str]] = None,
        scope: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return a page of records, or ``{"error": {...}}``."""

    async def aggregate(
        self,
        spool_id: str,
        *,
        group_by: Optional[list[str]] = None,
        aggregates: Optional[list[dict[str, Any]]] = None,
        filters: Optional[dict[str, Any]] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        limit: Optional[int] = None,
        page: int = 1,
        page_size: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return grouped aggregates, or ``{"error": {...}}``."""

    async def distinct(
        self,
        spool_id: str,
        column: str,
        *,
        limit: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return distinct values for ``column``, or ``{"error": {...}}``."""

    async def delete_spool(self, spool_id: str, *, scope: Optional[str] = None) -> bool:
        """Remove a spool. Returns False if absent or not visible to ``scope``."""


def _not_found(spool_id: str) -> dict[str, Any]:
    return {
        "error": {
            "message": f"Spool '{spool_id}' not found.",
            "recoverable": False,
        }
    }


class SQLiteSpoolBackend:
    """Default backend storing spools in a local SQLite database."""

    def __init__(self, config: "SpoolerConfig") -> None:
        self.config = config
        self._db: Optional[sqlite3.Connection] = None

    # -- async protocol surface ---------------------------------------------
    # SQLite calls are local and fast, so these await nothing; they exist so
    # the SQLite backend satisfies the same contract as a network backend.

    async def initialise(self) -> None:
        self._sync_initialise()

    async def cleanup(self) -> None:
        self._sync_cleanup()

    async def create_spool(  # NOSONAR(python:S7503) protocol requires a coroutine
        self, **kwargs: Any
    ) -> dict[str, Any]:
        return self._sync_create_spool(**kwargs)

    async def delete_spool(self, spool_id: str, *, scope: Optional[str] = None) -> bool:
        return self._sync_delete_spool(spool_id, scope=scope)

    async def list_spools(  # NOSONAR(python:S7503) protocol requires a coroutine
        self, *, scope: Optional[str] = None
    ) -> dict[str, Any]:
        return self._sync_list_spools(scope=scope)

    async def query(
        self, spool_id: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict[str, Any]:
        return self._sync_query(spool_id, scope=scope, **kw)

    async def aggregate(
        self, spool_id: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict[str, Any]:
        return self._sync_aggregate(spool_id, scope=scope, **kw)

    async def distinct(
        self,
        spool_id: str,
        column: str,
        *,
        limit: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._sync_distinct(spool_id, column, limit=limit, scope=scope)

    # -- lifecycle -----------------------------------------------------------

    def _sync_initialise(self) -> None:
        if self._db is not None:
            return
        self._db = sqlite3.connect(self.config.db_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()
        logger.info(
            "Response spooler initialised with database at %s",
            self.config.db_path,
        )

    def _sync_cleanup(self) -> None:
        if self._db is None:
            return
        self._db.close()
        self._db = None
        if self.config.db_cleanup_on_exit:
            db_path = Path(self.config.db_path)
            if db_path.exists():
                db_path.unlink()
                logger.info("Cleaned up spooler database at %s", db_path)

    @property
    def connection(self) -> sqlite3.Connection:
        """The live connection. Raises RuntimeError before initialise()."""
        if self._db is None:
            raise RuntimeError("Spooler not initialised.")
        return self._db

    def _create_schema(self) -> None:
        db = self.connection
        db.executescript("""
            CREATE TABLE IF NOT EXISTS _spool_registry (
                spool_id TEXT PRIMARY KEY,
                source_tool TEXT NOT NULL,
                array_path TEXT NOT NULL,
                table_name TEXT NOT NULL,
                total_records INTEGER NOT NULL,
                column_names TEXT NOT NULL,
                created_at TEXT NOT NULL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS _spool_stats (
                spool_id TEXT PRIMARY KEY,
                numeric_columns TEXT,
                min_values TEXT,
                max_values TEXT,
                distinct_counts TEXT,
                FOREIGN KEY (spool_id) REFERENCES _spool_registry(spool_id)
            );
            """)
        # Scope and expiry were added after the original schema; extend an
        # existing database in place so older spool files keep working.
        existing = {row[1] for row in db.execute("PRAGMA table_info(_spool_registry)")}
        if "scope" not in existing:
            db.execute("ALTER TABLE _spool_registry ADD COLUMN scope TEXT")
        if "expires_at" not in existing:
            db.execute("ALTER TABLE _spool_registry ADD COLUMN expires_at TEXT")
        db.commit()

    # -- writes --------------------------------------------------------------

    def _sync_create_spool(
        self,
        *,
        spool_id: str,
        source_tool: str,
        array_path: str,
        columns: list[str],
        column_types: dict[str, str],
        rows: list[tuple[Any, ...]],
        description: Optional[str] = None,
        scope: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> dict[str, Any]:
        db = self.connection
        table_name = f"spool_{spool_id}"

        col_defs = ", ".join(f'"{col}" {column_types[col]}' for col in columns)
        db.execute(
            f'CREATE TABLE IF NOT EXISTS "{table_name}" '
            f"(_row_id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
        )
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(f'"{c}"' for c in columns)
        db.executemany(
            f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
            rows,
        )

        stats = self._compute_stats(table_name, columns, column_types)

        now = datetime.now(timezone.utc)
        expires_at = (
            (now + timedelta(seconds=ttl)).isoformat() if ttl is not None else None
        )
        db.execute(
            """INSERT OR REPLACE INTO _spool_registry
               (spool_id, source_tool, array_path, table_name,
                total_records, column_names, created_at, description,
                scope, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                spool_id,
                source_tool,
                array_path,
                table_name,
                len(rows),
                json.dumps(columns),
                now.isoformat(),
                description,
                scope,
                expires_at,
            ),
        )
        db.execute(
            """INSERT OR REPLACE INTO _spool_stats
               (spool_id, numeric_columns, min_values, max_values, distinct_counts)
               VALUES (?, ?, ?, ?, ?)""",
            (
                spool_id,
                json.dumps(stats.get("numeric_columns", [])),
                json.dumps(stats.get("min_values", {})),
                json.dumps(stats.get("max_values", {})),
                json.dumps(stats.get("distinct_counts", {})),
            ),
        )
        db.commit()

        return {"stats": stats, "sample": self._get_sample(table_name, columns)}

    def _sync_delete_spool(self, spool_id: str, *, scope: Optional[str] = None) -> bool:
        db = self.connection
        row = self._visible_registry_row(spool_id, scope)
        if row is None:
            return False
        db.execute(f'DROP TABLE IF EXISTS "{row["table_name"]}"')
        db.execute("DELETE FROM _spool_stats WHERE spool_id = ?", [spool_id])
        db.execute("DELETE FROM _spool_registry WHERE spool_id = ?", [spool_id])
        db.commit()
        return True

    # -- reads ---------------------------------------------------------------

    def _sync_list_spools(self, *, scope: Optional[str] = None) -> dict[str, Any]:
        db = self.connection
        where, params = self._visibility_clause(scope)
        cursor = db.execute(
            f"""SELECT spool_id, source_tool, array_path, total_records,
                       column_names, created_at, description
                FROM _spool_registry {where}
                ORDER BY created_at DESC""",
            params,
        )
        spools = [
            {
                "spool_id": row[0],
                "source_tool": row[1],
                "array_path": row[2],
                "total_records": row[3],
                "columns": json.loads(row[4]),
                "created_at": row[5],
                "description": row[6],
            }
            for row in cursor.fetchall()
        ]
        return {"total_spools": len(spools), "spools": spools}

    def _sync_query(
        self, spool_id: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict[str, Any]:
        if self._visible_registry_row(spool_id, scope) is None:
            return _not_found(spool_id)
        return self._engine().query(spool_id=spool_id, **kw)

    def _sync_aggregate(
        self, spool_id: str, *, scope: Optional[str] = None, **kw: Any
    ) -> dict[str, Any]:
        if self._visible_registry_row(spool_id, scope) is None:
            return _not_found(spool_id)
        return self._engine().aggregate(spool_id=spool_id, **kw)

    def _sync_distinct(
        self,
        spool_id: str,
        column: str,
        *,
        limit: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> dict[str, Any]:
        if self._visible_registry_row(spool_id, scope) is None:
            return _not_found(spool_id)
        kwargs: dict[str, Any] = {"spool_id": spool_id, "column": column}
        if limit is not None:
            kwargs["limit"] = limit
        return self._engine().get_distinct_values(**kwargs)

    # -- helpers -------------------------------------------------------------

    def _engine(self) -> "QueryEngine":
        from spindl.spooler.query_engine import QueryEngine

        return QueryEngine(self.connection, self.config)

    @staticmethod
    def _visibility_clause(scope: Optional[str]) -> tuple[str, list[Any]]:
        now = datetime.now(timezone.utc).isoformat()
        clauses = ["(expires_at IS NULL OR expires_at > ?)"]
        params: list[Any] = [now]
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        return "WHERE " + " AND ".join(clauses), params

    def _visible_registry_row(
        self, spool_id: str, scope: Optional[str]
    ) -> Optional[sqlite3.Row]:
        where, params = self._visibility_clause(scope)
        cursor = self.connection.execute(
            f"SELECT * FROM _spool_registry {where} AND spool_id = ?",
            [*params, spool_id],
        )
        row: Optional[sqlite3.Row] = cursor.fetchone()
        return row

    def _compute_stats(
        self, table_name: str, columns: list[str], col_types: dict[str, str]
    ) -> dict[str, Any]:
        db = self.connection
        stats: dict[str, Any] = {
            "numeric_columns": [],
            "min_values": {},
            "max_values": {},
            "distinct_counts": {},
        }
        for col in columns:
            cursor = db.execute(f'SELECT COUNT(DISTINCT "{col}") FROM "{table_name}"')
            stats["distinct_counts"][col] = cursor.fetchone()[0]
            if col_types[col] in ("INTEGER", "REAL"):
                stats["numeric_columns"].append(col)
                cursor = db.execute(
                    f'SELECT MIN("{col}"), MAX("{col}") FROM "{table_name}"'
                )
                row = cursor.fetchone()
                stats["min_values"][col] = row[0]
                stats["max_values"][col] = row[1]
        return stats

    def _get_sample(self, table_name: str, columns: list[str]) -> list[dict[str, Any]]:
        col_names = ", ".join(f'"{c}"' for c in columns)
        cursor = self.connection.execute(
            f'SELECT {col_names} FROM "{table_name}" '
            f"LIMIT {self.config.summary_sample_size}"
        )
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
