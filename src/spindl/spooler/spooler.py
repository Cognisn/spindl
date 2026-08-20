"""Core Response Spooler.

Handles the ingestion of raw API JSON responses, detection and extraction
of array data, storage through a SpoolBackend (SQLite by default), and
generation of LLM-friendly summaries.

Guidance text uses @placeholder syntax for tool name references, which
are resolved by the PrefixResolver at the server level.
"""

import copy
import hashlib
import json
import logging
import secrets
import sqlite3
import time
from typing import Any, Optional

from spindl.spooler.backend import SpoolBackend, SQLiteSpoolBackend
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
        self.backend: SpoolBackend = self.config.backend or SQLiteSpoolBackend(
            self.config
        )
        self._initialised = False

    def initialise(self) -> None:
        """Initialise the storage backend.

        Synchronous convenience for the default SQLite backend and for
        callers outside an event loop. Use ``await initialise_async()``
        when a non-SQLite backend is configured.
        """
        if self._initialised:
            return
        if isinstance(self.backend, SQLiteSpoolBackend):
            self.backend._sync_initialise()
        else:
            _run_blocking(self.backend.initialise())
        self._initialised = True

    async def initialise_async(self) -> None:
        """Initialise the storage backend from within an event loop."""
        if self._initialised:
            return
        await self.backend.initialise()
        self._initialised = True

    def require_initialised(self) -> None:
        """Raise RuntimeError unless ``initialise()`` has been called."""
        if not self._initialised:
            raise RuntimeError("Spooler not initialised.")

    def current_scope(self) -> Optional[str]:
        """Scope applied to spools created or read in this request.

        Returns the authenticated caller's subject (or client id) when
        ``scope_from_identity`` is set and a request is authenticated,
        otherwise ``None``.
        """
        if not self.config.scope_from_identity:
            return None
        from spindl.auth import current_identity

        identity = current_identity()
        if identity is None:
            return None
        return identity.subject or identity.client_id

    async def process_response(
        self,
        response: dict[str, Any] | list[Any],
        source_tool: str,
        array_paths: Optional[list[str]] = None,
        description: Optional[str] = None,
        scope: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> dict[str, Any]:
        """Process an API response, spooling large arrays to the backend.

        Args:
            response: The raw API response as a parsed dict or list.
            source_tool: Name of the MCP tool that made the API call.
            array_paths: Optional list of dot-notation paths to arrays.
                If None, the spooler will auto-detect top-level arrays.
            description: Optional human-readable description of the data.
            scope: Owner of the resulting spools. Defaults to
                ``current_scope()``.
            ttl: Lifetime in seconds. Defaults to
                ``config.default_ttl_seconds``.

        Returns:
            A dict containing either the original response (if small
            enough) or a summary with spool references for large arrays.
        """
        if not self._initialised:
            raise RuntimeError(
                "Spooler not initialised. " "Call spooler.initialise() first."
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

        if scope is None:
            scope = self.current_scope()
        if ttl is None:
            ttl = self.config.default_ttl_seconds

        # Process each array path
        spooled_arrays = []
        remaining_response = self._deep_copy_without_arrays(response, array_paths)

        for path in array_paths:
            spool_info = await self._process_array_path(
                response,
                remaining_response,
                path,
                source_tool,
                description,
                scope,
                ttl,
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

    async def _process_array_path(
        self,
        response: dict[str, Any],
        remaining_response: dict[str, Any],
        path: str,
        source_tool: str,
        description: Optional[str],
        scope: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
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

        estimated_tokens = self.config.estimate_tokens(json.dumps(array_data))
        if (
            estimated_tokens <= self.config.max_inline_tokens
            and len(array_data) <= self.config.max_inline_items
        ):
            self._set_path(remaining_response, path, array_data)
            return None

        return await self._spool_array(
            array_data=array_data,
            source_tool=source_tool,
            array_path=path,
            description=description,
            scope=scope,
            ttl=ttl,
        )

    def _detect_arrays(
        self, data: dict[str, Any], prefix: str = "", max_depth: int = 3
    ) -> list[str]:
        """Auto-detect array fields in a response, up to max_depth."""
        arrays: list[str] = []
        if max_depth <= 0:
            return arrays

        for key, value in data.items():
            current_path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, list) and len(value) > 0:
                if isinstance(value[0], dict):
                    arrays.append(current_path)
            elif isinstance(value, dict):
                arrays.extend(self._detect_arrays(value, current_path, max_depth - 1))

        return arrays

    def _extract_path(self, data: dict[str, Any], path: str) -> Any:
        """Extract a value from a nested dict using dot notation."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _set_path(self, data: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
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
        self, data: dict[str, Any], array_paths: list[str]
    ) -> dict[str, Any]:
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

    async def _spool_array(
        self,
        array_data: list[dict[str, Any]],
        source_tool: str,
        array_path: str,
        description: Optional[str] = None,
        scope: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> dict[str, Any]:
        """Flatten an array and store it through the backend."""
        spool_id = self._generate_spool_id(source_tool, array_path)

        columns, rows = self._flatten_array(array_data)
        col_types = self._infer_column_types(columns, rows)

        stored = await self.backend.create_spool(
            spool_id=spool_id,
            source_tool=source_tool,
            array_path=array_path,
            columns=columns,
            column_types=col_types,
            rows=rows,
            description=description,
            scope=scope,
            ttl=ttl,
        )

        return {
            "spool_id": spool_id,
            "array_path": array_path,
            "total_records": len(rows),
            "columns": columns,
            "column_types": col_types,
            "stats": stored["stats"],
            "sample": stored["sample"],
        }

    def _flatten_array(
        self, array_data: list[dict[str, Any]]
    ) -> tuple[list[str], list[tuple[Any, ...]]]:
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
        self, d: dict[str, Any], prefix: str = "", separator: str = "."
    ) -> dict[str, Any]:
        """Flatten a nested dictionary with dot-separated keys."""
        items: dict[str, Any] = {}
        for key, value in d.items():
            new_key = f"{prefix}{separator}{key}" if prefix else key
            if isinstance(value, dict):
                items.update(self._flatten_dict(value, new_key, separator))
            elif isinstance(value, list):
                items[new_key] = json.dumps(value)
            else:
                items[new_key] = value
        return items

    def _infer_column_types(
        self, columns: list[str], rows: list[tuple[Any, ...]]
    ) -> dict[str, str]:
        """Infer SQLite column types from the actual data values."""
        types: dict[str, str] = {}
        for i, col in enumerate(columns):
            col_values = [row[i] for row in rows if row[i] is not None]
            if not col_values:
                types[col] = "TEXT"
                continue

            all_int = all(isinstance(v, int) for v in col_values)
            all_numeric = all(isinstance(v, (int, float)) for v in col_values)

            if all_int:
                types[col] = "INTEGER"
            elif all_numeric:
                types[col] = "REAL"
            else:
                types[col] = "TEXT"

        return types

    def _build_summary(
        self,
        remaining_response: dict[str, Any],
        spooled_arrays: list[dict[str, Any]],
        source_tool: str,
    ) -> dict[str, Any]:
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
                    "distinct_value_counts": (spool["stats"]["distinct_counts"]),
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

    def _size_guard(self, response: dict[str, Any]) -> dict[str, Any]:
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
        """Generate a short, unique spool ID.

        Mixes in random bytes as well as the clock: ``time.time_ns()`` has
        coarse resolution on some platforms (about 15 ms on Windows), so
        two spools created in quick succession from the same tool and path
        would otherwise collide and the second would overwrite the first.
        """
        timestamp = str(time.time_ns())
        raw = f"{source_tool}:{array_path}:{timestamp}:{secrets.token_hex(8)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def cleanup(self) -> None:
        """Release the backend's resources (synchronous convenience)."""
        if not self._initialised:
            return
        if isinstance(self.backend, SQLiteSpoolBackend):
            self.backend._sync_cleanup()
        else:
            _run_blocking(self.backend.cleanup())
        self._initialised = False

    async def cleanup_async(self) -> None:
        """Release the backend's resources from within an event loop."""
        if self._initialised:
            await self.backend.cleanup()
            self._initialised = False

    def get_connection(self) -> sqlite3.Connection:
        """Return the SQLite connection when the default backend is in use.

        Retained for callers that drive ``QueryEngine`` directly. Raises
        RuntimeError if the spooler is not initialised or a non-SQLite
        backend is configured.
        """
        if not self._initialised:
            raise RuntimeError("Spooler not initialised.")
        if not isinstance(self.backend, SQLiteSpoolBackend):
            raise RuntimeError(
                "get_connection() is only available with the SQLite backend."
            )
        return self.backend.connection


def _run_blocking(coro: Any) -> Any:
    """Run a coroutine to completion from synchronous code.

    Used by the synchronous ``initialise()`` and ``cleanup()`` conveniences
    when a non-SQLite backend is configured and no event loop is running.
    Raises RuntimeError inside a running loop; use the ``*_async`` variants
    there.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise RuntimeError(
        "Cannot block on an async backend inside a running event loop; "
        "use initialise_async() / cleanup_async()."
    )
