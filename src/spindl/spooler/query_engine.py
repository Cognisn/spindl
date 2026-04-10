"""Query Engine for spooled data.

Provides safe, parameterised SQL queries over spooled array data,
with pagination, filtering, sorting, and basic aggregation.
"""

import json
import re
import sqlite3
import logging
from typing import Any, Optional

from spindl.spooler.config import SpoolerConfig

logger = logging.getLogger(__name__)

ALLOWED_OPERATORS = {
    "eq": "=",
    "neq": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "not_like": "NOT LIKE",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
    "in": "IN",
}

ALLOWED_AGGREGATES = {
    "count", "countdistinct", "sum", "avg", "min", "max",
}

SAFE_COLUMN_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


class QueryEngine:
    """Provides safe query capabilities over spooled data.

    All user-supplied values are passed as parameters, never
    interpolated into SQL strings. Column names are validated
    against the registered schema before use.
    """

    def __init__(
        self,
        db: sqlite3.Connection,
        config: Optional[SpoolerConfig] = None,
    ) -> None:
        self.db = db
        self.config = config or SpoolerConfig()

    def list_spools(self) -> dict:
        """List all available spools with their metadata."""
        cursor = self.db.execute(
            """SELECT r.spool_id, r.source_tool, r.array_path,
                      r.total_records, r.column_names, r.created_at,
                      r.description
               FROM _spool_registry r
               ORDER BY r.created_at DESC"""
        )
        rows = cursor.fetchall()

        spools = []
        for row in rows:
            spools.append({
                "spool_id": row[0],
                "source_tool": row[1],
                "array_path": row[2],
                "total_records": row[3],
                "columns": json.loads(row[4]),
                "created_at": row[5],
                "description": row[6],
            })

        return {
            "total_spools": len(spools),
            "spools": spools,
        }

    def query(
        self,
        spool_id: str,
        columns: Optional[list[str]] = None,
        filters: Optional[list[dict]] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc",
        page: int = 1,
        page_size: Optional[int] = None,
        search: Optional[str] = None,
        search_columns: Optional[list[str]] = None,
    ) -> dict:
        """Query spooled data with filtering, sorting, and pagination."""
        registry = self._get_spool_registry(spool_id)
        if not registry:
            return self._error(f"Spool '{spool_id}' not found.")

        table_name = registry["table_name"]
        valid_columns = json.loads(registry["column_names"])

        page_size = min(
            page_size or self.config.default_page_size,
            self.config.max_page_size,
        )
        page = max(1, page)
        offset = (page - 1) * page_size

        select_cols = self._validate_columns(columns, valid_columns)
        if isinstance(select_cols, dict):
            return select_cols

        where_clause, where_params = self._build_where(
            filters, valid_columns
        )
        if isinstance(where_clause, dict):
            return where_clause

        search_clause, search_params = self._build_search(
            search, search_columns, valid_columns, table_name
        )
        if where_clause and search_clause:
            where_clause = f"{where_clause} AND {search_clause}"
            where_params.extend(search_params)
        elif search_clause:
            where_clause = search_clause
            where_params = search_params

        order_clause = ""
        if sort_by:
            if not self._is_valid_column(sort_by, valid_columns):
                return self._error(
                    f"Invalid sort column '{sort_by}'. "
                    f"Valid columns: {valid_columns}"
                )
            direction = "DESC" if sort_order.lower() == "desc" else "ASC"
            order_clause = f'ORDER BY "{sort_by}" {direction}'

        col_expr = ", ".join(f'"{c}"' for c in select_cols)
        full_where = f"WHERE {where_clause}" if where_clause else ""

        count_sql = (
            f'SELECT COUNT(*) FROM "{table_name}" {full_where}'
        )
        total = self.db.execute(count_sql, where_params).fetchone()[0]

        query_sql = (
            f'SELECT {col_expr} FROM "{table_name}" '
            f"{full_where} {order_clause} "
            f"LIMIT ? OFFSET ?"
        )
        params = where_params + [page_size, offset]
        cursor = self.db.execute(query_sql, params)
        rows = cursor.fetchall()

        results = [dict(zip(select_cols, row)) for row in rows]

        total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "spool_id": spool_id,
            "results": results,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
            },
            "query_info": {
                "columns_returned": select_cols,
                "filters_applied": filters or [],
                "sort": (
                    f"{sort_by} {sort_order}" if sort_by else "default"
                ),
                "search": search,
            },
        }

    def aggregate(
        self,
        spool_id: str,
        group_by: Optional[list[str]] = None,
        aggregates: Optional[list[dict]] = None,
        filters: Optional[list[dict]] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        limit: int = 50,
        page: int = 1,
        page_size: Optional[int] = None,
    ) -> dict:
        """Aggregate spooled data with grouping and filters."""
        registry = self._get_spool_registry(spool_id)
        if not registry:
            return self._error(f"Spool '{spool_id}' not found.")

        table_name = registry["table_name"]
        valid_columns = json.loads(registry["column_names"])

        if not aggregates:
            aggregates = [
                {"function": "count", "column": "*", "alias": "total"}
            ]

        agg_result = self._build_aggregate_exprs(
            aggregates, valid_columns
        )
        if isinstance(agg_result, dict):
            return agg_result
        agg_exprs, agg_aliases = agg_result

        group_result = self._build_group_cols(group_by, valid_columns)
        if isinstance(group_result, dict):
            return group_result
        group_cols = group_result

        where_clause, where_params = self._build_where(
            filters, valid_columns
        )
        if isinstance(where_clause, dict):
            return where_clause

        full_where = f"WHERE {where_clause}" if where_clause else ""
        group_clause = (
            f"GROUP BY {', '.join(group_cols)}" if group_cols else ""
        )

        select_parts = list(group_cols) + agg_exprs
        select_expr = ", ".join(select_parts)

        order_clause = self._build_agg_order(
            sort_by, sort_order, group_cols, agg_aliases, valid_columns
        )

        return self._execute_aggregate(
            table_name=table_name,
            select_expr=select_expr,
            full_where=full_where,
            group_clause=group_clause,
            order_clause=order_clause,
            where_params=where_params,
            group_cols=group_cols,
            agg_aliases=agg_aliases,
            spool_id=spool_id,
            group_by=group_by,
            aggregates=aggregates,
            filters=filters,
            limit=limit,
            page=page,
            page_size=page_size,
        )

    def get_distinct_values(
        self,
        spool_id: str,
        column: str,
        limit: int = 50,
    ) -> dict:
        """Get distinct values for a column with frequency counts."""
        registry = self._get_spool_registry(spool_id)
        if not registry:
            return self._error(f"Spool '{spool_id}' not found.")

        table_name = registry["table_name"]
        valid_columns = json.loads(registry["column_names"])

        if not self._is_valid_column(column, valid_columns):
            return self._error(
                f"Invalid column '{column}'. "
                f"Valid columns: {valid_columns}"
            )

        limit = min(max(1, limit), 500)

        cursor = self.db.execute(
            f'SELECT "{column}", COUNT(*) as count '
            f'FROM "{table_name}" '
            f'GROUP BY "{column}" '
            f"ORDER BY count DESC LIMIT ?",
            [limit],
        )
        rows = cursor.fetchall()

        return {
            "spool_id": spool_id,
            "column": column,
            "distinct_values": [
                {"value": row[0], "count": row[1]} for row in rows
            ],
            "total_distinct": len(rows),
        }

    # ------------------------------------------------------------------
    # Aggregate helpers
    # ------------------------------------------------------------------

    def _build_aggregate_exprs(
        self,
        aggregates: list[dict],
        valid_columns: list[str],
    ) -> tuple[list[str], list[str]] | dict:
        """Build SQL aggregate expressions from aggregate definitions."""
        agg_exprs = []
        agg_aliases = []

        for agg in aggregates:
            func = agg.get("function", "").lower()
            col = agg.get("column", "*")
            alias = agg.get("alias", f"{func}_{col}")

            if func not in ALLOWED_AGGREGATES:
                return self._error(
                    f"Invalid aggregate function '{func}'. "
                    f"Allowed: {sorted(ALLOWED_AGGREGATES)}"
                )

            result = self._build_single_agg_expr(
                func, col, alias, valid_columns
            )
            if isinstance(result, dict):
                return result
            agg_exprs.append(result)
            agg_aliases.append(re.sub(r"\W", "_", alias))

        return agg_exprs, agg_aliases

    def _build_single_agg_expr(
        self,
        func: str,
        col: str,
        alias: str,
        valid_columns: list[str],
    ) -> str | dict:
        """Build a single SQL aggregate expression."""
        safe_alias = re.sub(r"\W", "_", alias)

        if func == "countdistinct":
            if col == "*":
                return self._error(
                    "countdistinct requires a column name, not '*'."
                )
            if not self._is_valid_column(col, valid_columns):
                return self._error(
                    f"Invalid column '{col}' for aggregation."
                )
            return f'COUNT(DISTINCT "{col}") AS "{safe_alias}"'

        if col != "*" and not self._is_valid_column(col, valid_columns):
            return self._error(
                f"Invalid column '{col}' for aggregation."
            )

        col_ref = "*" if col == "*" else f'"{col}"'
        return f'{func.upper()}({col_ref}) AS "{safe_alias}"'

    def _build_group_cols(
        self,
        group_by: Optional[list[str]],
        valid_columns: list[str],
    ) -> list[str] | dict:
        """Validate and build quoted group-by column references."""
        if not group_by:
            return []

        group_cols = []
        for col in group_by:
            if not self._is_valid_column(col, valid_columns):
                return self._error(
                    f"Invalid group_by column '{col}'."
                )
            group_cols.append(f'"{col}"')
        return group_cols

    def _build_agg_order(
        self,
        sort_by: Optional[str],
        sort_order: str,
        group_cols: list[str],
        agg_aliases: list[str],
        valid_columns: list[str],
    ) -> str:
        """Build an ORDER BY clause for aggregate queries."""
        if not sort_by:
            return ""

        all_valid = (
            [col.strip('"') for col in group_cols] + agg_aliases
        )
        if sort_by in all_valid or sort_by in valid_columns:
            direction = (
                "DESC" if sort_order.lower() == "desc" else "ASC"
            )
            return f'ORDER BY "{sort_by}" {direction}'
        return ""

    def _execute_aggregate(
        self,
        *,
        table_name: str,
        select_expr: str,
        full_where: str,
        group_clause: str,
        order_clause: str,
        where_params: list,
        group_cols: list[str],
        agg_aliases: list[str],
        spool_id: str,
        group_by: Optional[list[str]],
        aggregates: list[dict],
        filters: Optional[list[dict]],
        limit: int,
        page: int,
        page_size: Optional[int],
    ) -> dict:
        """Execute the aggregate query with optional pagination."""
        use_pagination = page_size is not None or page > 1

        if use_pagination:
            effective_page_size = min(
                page_size or self.config.default_page_size,
                self.config.max_page_size * 10,
            )
            page = max(1, page)
            offset = (page - 1) * effective_page_size

            inner_sql = (
                f'SELECT 1 FROM "{table_name}" '
                f"{full_where} {group_clause}"
            )
            count_sql = f"SELECT COUNT(*) FROM ({inner_sql})"
            total_groups = self.db.execute(
                count_sql, where_params
            ).fetchone()[0]

            query_sql = (
                f'SELECT {select_expr} FROM "{table_name}" '
                f"{full_where} {group_clause} {order_clause} "
                f"LIMIT ? OFFSET ?"
            )
            params = where_params + [effective_page_size, offset]
        else:
            effective_limit = min(
                max(1, limit), self.config.max_page_size * 10
            )
            query_sql = (
                f'SELECT {select_expr} FROM "{table_name}" '
                f"{full_where} {group_clause} {order_clause} LIMIT ?"
            )
            params = where_params + [effective_limit]

        cursor = self.db.execute(query_sql, params)
        rows = cursor.fetchall()

        result_columns = (
            [col.strip('"') for col in group_cols] + agg_aliases
        )
        results = [dict(zip(result_columns, row)) for row in rows]

        result: dict[str, Any] = {
            "spool_id": spool_id,
            "results": results,
            "total_groups": len(results),
            "aggregation_info": {
                "group_by": group_by or [],
                "aggregates": aggregates,
                "filters_applied": filters or [],
            },
        }

        if use_pagination:
            total_pages = max(
                1,
                (total_groups + effective_page_size - 1)
                // effective_page_size,
            )
            result["total_groups"] = total_groups
            result["pagination"] = {
                "page": page,
                "page_size": effective_page_size,
                "total_groups": total_groups,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
            }

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_spool_registry(self, spool_id: str) -> Optional[dict]:
        """Fetch spool metadata from the registry."""
        cursor = self.db.execute(
            "SELECT * FROM _spool_registry WHERE spool_id = ?",
            [spool_id],
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "spool_id": row[0],
            "source_tool": row[1],
            "array_path": row[2],
            "table_name": row[3],
            "total_records": row[4],
            "column_names": row[5],
            "created_at": row[6],
            "description": row[7],
        }

    def _validate_columns(
        self,
        requested: Optional[list[str]],
        valid: list[str],
    ) -> list[str] | dict:
        """Validate requested columns against the schema."""
        if requested is None:
            return valid

        invalid = [c for c in requested if c not in valid]
        if invalid:
            return self._error(
                f"Invalid columns: {invalid}. Valid columns: {valid}"
            )
        return requested

    def _is_valid_column(
        self, col: str, valid_columns: list[str]
    ) -> bool:
        """Check if a column name is valid and safe."""
        return (
            col in valid_columns
            and SAFE_COLUMN_PATTERN.match(col) is not None
        )

    def _build_where(
        self,
        filters: Optional[list[dict]],
        valid_columns: list[str],
    ) -> tuple[str, list] | tuple[dict, list]:
        """Build a parameterised WHERE clause from filter dicts."""
        if not filters:
            return "", []

        clauses = []
        params: list[Any] = []

        for f in filters:
            col = f.get("column", "")
            op_key = f.get("operator", "eq")
            value = f.get("value")

            if not self._is_valid_column(col, valid_columns):
                return (
                    self._error(
                        f"Invalid filter column '{col}'. "
                        f"Valid columns: {valid_columns}"
                    ),
                    [],
                )

            if op_key not in ALLOWED_OPERATORS:
                return (
                    self._error(
                        f"Invalid operator '{op_key}'. "
                        f"Allowed: {list(ALLOWED_OPERATORS.keys())}"
                    ),
                    [],
                )

            sql_op = ALLOWED_OPERATORS[op_key]

            if op_key in ("is_null", "is_not_null"):
                clauses.append(f'"{col}" {sql_op}')
            elif op_key == "in":
                if not isinstance(value, list) or len(value) == 0:
                    return (
                        self._error(
                            "The 'in' operator requires a non-empty "
                            "list value."
                        ),
                        [],
                    )
                placeholders = ", ".join(["?"] * len(value))
                clauses.append(f'"{col}" IN ({placeholders})')
                params.extend(value)
            else:
                clauses.append(f'"{col}" {sql_op} ?')
                params.append(value)

        return " AND ".join(clauses), params

    def _build_search(
        self,
        search: Optional[str],
        search_columns: Optional[list[str]],
        valid_columns: list[str],
        table_name: str,
    ) -> tuple[str, list]:
        """Build a LIKE-based search clause across text columns."""
        if not search:
            return "", []

        if search_columns:
            cols = [
                c
                for c in search_columns
                if self._is_valid_column(c, valid_columns)
            ]
        else:
            cols = []
            for col in valid_columns:
                cursor = self.db.execute(
                    f'SELECT typeof("{col}") FROM "{table_name}" '
                    f'WHERE "{col}" IS NOT NULL LIMIT 1'
                )
                row = cursor.fetchone()
                if row and row[0] == "text":
                    cols.append(col)

        if not cols:
            return "", []

        like_clauses = [f'"{c}" LIKE ?' for c in cols]
        search_term = f"%{search}%"
        params = [search_term] * len(cols)

        return f"({' OR '.join(like_clauses)})", params

    def _error(self, message: str) -> dict:
        """Create a standardised error response."""
        return {
            "error": {
                "message": message,
                "recoverable": True,
            }
        }
