"""DuckDB warehouse. All SQL lives in sql/<stage>/*.sql; this module only runs it."""

from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
LOADABLE = ("actual_daily", "published_hourly", "live_forecast")  # identifier allowlist


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text(encoding="utf-8")).fetchall()  # drain: duckdb 2 keeps results open


def connect(path: str | Path = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    run_sql_file(con, SQL_DIR / "raw" / "00_create_raw.sql")
    return con


def load(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Upsert df into raw_<table>; returns the table's row count afterwards."""
    if table not in LOADABLE:
        raise ValueError(f"unknown table {table!r}; expected one of {LOADABLE}")
    con.register("incoming", df)
    try:
        run_sql_file(con, SQL_DIR / "raw" / f"load_{table}.sql")
    finally:
        con.unregister("incoming")
    return con.execute(f"select count(*) from raw_{table}").fetchall()[0][0]


def build_models(con: duckdb.DuckDBPyConnection) -> None:
    for stage in ("staging", "marts"):
        for path in sorted((SQL_DIR / stage).glob("*.sql")):
            run_sql_file(con, path)


def snapshot(con: duckdb.DuckDBPyConnection, table: str, n: int = 5) -> dict:
    """Schema, row count and first n rows, for the results page."""
    names = {
        r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()
    }
    if table not in names:
        raise ValueError(f"unknown table {table!r}")
    cols = con.execute(f"describe {table}").fetchall()
    count = con.execute(f"select count(*) from {table}").fetchall()[0][0]
    sample = con.execute(f"select * from {table} order by all limit {int(n)}").fetchall()
    return {
        "table": table,
        "row_count": count,
        "columns": [[c[0], c[1]] for c in cols],
        "sample": [
            [None if v is None else str(v) if not isinstance(v, int | float) else v for v in row]
            for row in sample
        ],
    }
