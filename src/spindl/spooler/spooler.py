"""Core Response Spooler.

Handles the ingestion of raw API JSON responses, detection and extraction
of array data, storage in SQLite, and generation of LLM-friendly summaries.

Guidance text uses @placeholder syntax for tool name references, which
are resolved by the PrefixResolver at the server level.
"""

import copy
import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spindl.spooler.config import SpoolerConfig

logger = logging.getLogger(__name__)


class ResponseSpooler:
    """Intercepts large API responses and spools array data to SQLite.

    The spooler sits between the raw API response and the MCP tool return
    value. It examines the response JSON, identifies arrays that exceed
    the configured inline threshold, stores them in SQLite, and returns
    a summary with metadata that allows the LLM to query the data using
    the generic spooler query tools.

    Usage::

        spooler = ResponseSpooler(config)
        spooler.initialise()

        result = spooler.process_response(
            response=raw_response,
            source_tool="list_cves",
            array_paths=["vulnerabilities"],
        )
    """

    def __init__(self, config: Optional[SpoolerConfig] = None) -> None:
        self.config = config or SpoolerConfig()
        self.config.validate()
        self._db: Optional[sqlite3.Connection] = None
        self._initialised = False

    def initialise(self) -> None:
        """Initialise the SQLite database and create schema tables."""
        if self._initialised:
            return

        self._db = sqlite3.connect(self.config.db_path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")

        self._create_schema()
        self._initialised = True
        logger.info(
            "Response spooler initialised with database at %s",
            self.config.db_path,
        )

    def _create_schema(self) -> None:
        """Create the metadata and registry tables."""
        self._db.executescript("""
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
        self._db.commit()

    def process_response(
        self,
        response: dict | list,
        source_tool: str,
        array_paths: Optional[list[str]] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Process an API response, spooling large arrays to SQLite.

        Args:
            response: The raw API response as a parsed dict or list.
            source_tool: Name of the MCP tool that made the API call.
            array_paths: Optional list of dot-notation paths to arrays.
                If None, the spooler will auto-detect top-level arrays.
            description: Optional human-readable description of the data.

        Returns:
            A dict containing either the original response (if small
            enough) or a summary with spool references for large arrays.
        """
        if not self._initialised:
            raise RuntimeError(
                "Spooler not initialised. "
                "Call spooler.initialise() first."
            )

        # If the response itself is an array, wrap it
        if isinstance(response, list):
            response = {"results": response}
            if array_paths is None:
                array_paths = ["results"]

        # Auto-detect arrays if no paths specified
        if array_paths is None:
            array_paths = self._detect_arrays(response)

        if not array_paths:
            return self._size_guard(response)

        # Process each array path
        spooled_arrays = []
        remaining_response = self._deep_copy_without_arrays(
            response, array_paths
        )

        for path in array_paths:
            spool_info = self._process_array_path(
                response, remaining_response, path,
                source_tool, description,
            )
            if spool_info is not None:
                spooled_arrays.append(spool_info)

        if not spooled_arrays:
            return self._size_guard(remaining_response)

        return self._build_summary(
            remaining_response=remaining_response,
            spooled_arrays=spooled_arrays,
            source_tool=source_tool,
        )

    def _process_array_path(
        self,
        response: dict,
        remaining_response: dict,
        path: str,
        source_tool: str,
        description: Optional[str],
    ) -> Optional[dict]:
        """Process a single array path, returning spool info if spooled."""
        array_data = self._extract_path(response, path)
        if array_data is None or not isinstance(array_data, list):
            logger.warning(
                "Path '%s' did not resolve to an array, skipping.",
                path,
            )
            return None

        if len(array_data) == 0:
            self._set_path(remaining_response, path, [])
            return None

        estimated_tokens = self.config.estimate_tokens(
            json.dumps(array_data)
        )
        if (
            estimated_tokens <= self.config.max_inline_tokens
            and len(array_data) <= self.config.max_inline_items
        ):
            self._set_path(remaining_response, path, array_data)
            return None

        return self._spool_array(
            array_data=array_data,
            source_tool=source_tool,
            array_path=path,
            description=description,
        )

    def _detect_arrays(
        self, data: dict, prefix: str = "", max_depth: int = 3
    ) -> list[str]:
        """Auto-detect array fields in a response, up to max_depth."""
        arrays = []
        if max_depth <= 0:
            return arrays

        for key, value in data.items():
            current_path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, list) and len(value) > 0:
                if isinstance(value[0], dict):
                    arrays.append(current_path)
            elif isinstance(value, dict):
                arrays.extend(
                    self._detect_arrays(value, current_path, max_depth - 1)
                )

        return arrays

    def _extract_path(self, data: dict, path: str) -> Any:
        """Extract a value from a nested dict using dot notation."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _set_path(self, data: dict, path: str, value: Any) -> dict:
        """Set a value in a nested dict using dot notation."""
        parts = path.split(".")
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        return data

    def _deep_copy_without_arrays(
        self, data: dict, array_paths: list[str]
    ) -> dict:
        """Create a copy of the response with spooled arrays removed."""
        result = copy.deepcopy(data)
        for path in array_paths:
            parts = path.split(".")
            current = result
            for part in parts[:-1]:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    break
            else:
                if isinstance(current, dict) and parts[-1] in current:
                    del current[parts[-1]]
        return result

    def _spool_array(
        self,
        array_data: list[dict],
        source_tool: str,
        array_path: str,
        description: Optional[str] = None,
    ) -> dict:
        """Store an array of objects in a dynamically created SQLite table."""
        spool_id = self._generate_spool_id(source_tool, array_path)
        table_name = f"spool_{spool_id}"

        columns, rows = self._flatten_array(array_data)
        col_types = self._infer_column_types(columns, rows)

        col_defs = ", ".join(
            f'"{col}" {col_types[col]}' for col in columns
        )
        self._db.execute(
            f'CREATE TABLE IF NOT EXISTS "{table_name}" '
            f"(_row_id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
        )

        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(f'"{c}"' for c in columns)
        self._db.executemany(
            f'INSERT INTO "{table_name}" ({col_names}) '
            f"VALUES ({placeholders})",
            rows,
        )

        stats = self._compute_stats(table_name, columns, col_types)

        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT OR REPLACE INTO _spool_registry
               (spool_id, source_tool, array_path, table_name,
                total_records, column_names, created_at, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                spool_id,
                source_tool,
                array_path,
                table_name,
                len(rows),
                json.dumps(columns),
                now,
                description,
            ),
        )

        self._db.execute(
            """INSERT OR REPLACE INTO _spool_stats
               (spool_id, numeric_columns, min_values,
                max_values, distinct_counts)
               VALUES (?, ?, ?, ?, ?)""",
            (
                spool_id,
                json.dumps(stats.get("numeric_columns", [])),
                json.dumps(stats.get("min_values", {})),
                json.dumps(stats.get("max_values", {})),
                json.dumps(stats.get("distinct_counts", {})),
            ),
        )

        self._db.commit()

        sample = self._get_sample(table_name, columns)

        return {
            "spool_id": spool_id,
            "array_path": array_path,
            "table_name": table_name,
            "total_records": len(rows),
            "columns": columns,
            "column_types": col_types,
            "stats": stats,
            "sample": sample,
        }

    def _flatten_array(
        self, array_data: list[dict]
    ) -> tuple[list[str], list[tuple]]:
        """Flatten an array of potentially nested dicts into tabular form."""
        all_keys: dict[str, None] = {}
        for item in array_data:
            flat = self._flatten_dict(item)
            for key in flat:
                if key not in all_keys:
                    all_keys[key] = None

        columns = list(all_keys.keys())

        rows = []
        for item in array_data:
            flat = self._flatten_dict(item)
            row = []
            for col in columns:
                value = flat.get(col)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                row.append(value)
            rows.append(tuple(row))

        return columns, rows

    def _flatten_dict(
        self, d: dict, prefix: str = "", separator: str = "."
    ) -> dict:
        """Flatten a nested dictionary with dot-separated keys."""
        items: dict[str, Any] = {}
        for key, value in d.items():
            new_key = f"{prefix}{separator}{key}" if prefix else key
            if isinstance(value, dict):
                items.update(
                    self._flatten_dict(value, new_key, separator)
                )
            elif isinstance(value, list):
                items[new_key] = json.dumps(value)
            else:
                items[new_key] = value
        return items

    def _infer_column_types(
        self, columns: list[str], rows: list[tuple]
    ) -> dict[str, str]:
        """Infer SQLite column types from the actual data values."""
        types: dict[str, str] = {}
        for i, col in enumerate(columns):
            col_values = [row[i] for row in rows if row[i] is not None]
            if not col_values:
                types[col] = "TEXT"
                continue

            all_int = all(isinstance(v, int) for v in col_values)
            all_numeric = all(
                isinstance(v, (int, float)) for v in col_values
            )

            if all_int:
                types[col] = "INTEGER"
            elif all_numeric:
                types[col] = "REAL"
            else:
                types[col] = "TEXT"

        return types

    def _compute_stats(
        self,
        table_name: str,
        columns: list[str],
        col_types: dict[str, str],
    ) -> dict:
        """Compute basic statistics on the spooled data."""
        stats: dict[str, Any] = {
            "numeric_columns": [],
            "min_values": {},
            "max_values": {},
            "distinct_counts": {},
        }

        for col in columns:
            cursor = self._db.execute(
                f'SELECT COUNT(DISTINCT "{col}") FROM "{table_name}"'
            )
            stats["distinct_counts"][col] = cursor.fetchone()[0]

            if col_types[col] in ("INTEGER", "REAL"):
                stats["numeric_columns"].append(col)
                cursor = self._db.execute(
                    f'SELECT MIN("{col}"), MAX("{col}") '
                    f'FROM "{table_name}"'
                )
                row = cursor.fetchone()
                stats["min_values"][col] = row[0]
                stats["max_values"][col] = row[1]

        return stats

    def _get_sample(
        self, table_name: str, columns: list[str]
    ) -> list[dict]:
        """Retrieve a small sample of records for the LLM summary."""
        col_names = ", ".join(f'"{c}"' for c in columns)
        cursor = self._db.execute(
            f'SELECT {col_names} FROM "{table_name}" '
            f"LIMIT {self.config.summary_sample_size}"
        )
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def _build_summary(
        self,
        remaining_response: dict,
        spooled_arrays: list[dict],
        source_tool: str,
    ) -> dict:
        """Build the LLM-friendly summary response.

        Uses @placeholder syntax for tool name references which
        are resolved by the PrefixResolver at the server level.
        """
        spool_summaries = []
        for spool in spooled_arrays:
            summary: dict[str, Any] = {
                "spool_id": spool["spool_id"],
                "source_array": spool["array_path"],
                "total_records": spool["total_records"],
                "columns": spool["columns"],
                "column_types": spool["column_types"],
                "statistics": {
                    "distinct_value_counts": (
                        spool["stats"]["distinct_counts"]
                    ),
                },
                "sample_records": spool["sample"],
                "query_hint": (
                    f"Use '@spooler_query' with spool_id "
                    f"'{spool['spool_id']}' to query this data. "
                    f"You can filter, sort, and paginate through "
                    f"{spool['total_records']} records."
                ),
            }
            if spool["stats"]["numeric_columns"]:
                summary["statistics"]["numeric_ranges"] = {
                    col: {
                        "min": spool["stats"]["min_values"].get(col),
                        "max": spool["stats"]["max_values"].get(col),
                    }
                    for col in spool["stats"]["numeric_columns"]
                }
            spool_summaries.append(summary)

        return {
            "response_data": remaining_response,
            "spooled_data": spool_summaries,
            "_spooler_meta": {
                "source_tool": source_tool,
                "total_spools": len(spooled_arrays),
                "total_spooled_records": sum(
                    s["total_records"] for s in spooled_arrays
                ),
                "instructions": (
                    "Large arrays have been stored for efficient "
                    "querying. Use '@spooler_query' to retrieve "
                    "filtered/paginated data, '@spooler_aggregate' "
                    "for counts and grouping, or '@spooler_list' "
                    "to see all available spools."
                ),
            },
        }

    def _size_guard(self, response: dict) -> dict:
        """Apply size guard to non-array responses."""
        serialised = json.dumps(response)
        estimated_tokens = self.config.estimate_tokens(serialised)

        if estimated_tokens <= self.config.max_inline_tokens * 2:
            return response

        return {
            "response_data": response,
            "_size_warning": {
                "estimated_tokens": estimated_tokens,
                "note": (
                    "This response is large. Consider requesting "
                    "specific fields or a filtered view."
                ),
            },
        }

    def _generate_spool_id(self, source_tool: str, array_path: str) -> str:
        """Generate a short, unique spool ID."""
        timestamp = str(time.time_ns())
        raw = f"{source_tool}:{array_path}:{timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def cleanup(self) -> None:
        """Close the database and optionally remove the file."""
        if self._db:
            self._db.close()
            self._db = None
            self._initialised = False

            if self.config.db_cleanup_on_exit:
                db_path = Path(self.config.db_path)
                if db_path.exists():
                    db_path.unlink()
                    logger.info(
                        "Cleaned up spooler database at %s", db_path
                    )

    def get_connection(self) -> sqlite3.Connection:
        """Return the database connection for use by the query engine."""
        if not self._initialised or not self._db:
            raise RuntimeError("Spooler not initialised.")
        return self._db
