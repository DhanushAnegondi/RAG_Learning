"""DuckDB warehouse. All SQL lives in sql/<stage>/*.sql; this module only runs it."""

from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text(encoding="utf-8")).fetchall()  # drain: duckdb 2 keeps results open


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return con.execute(f"select count(*) from {table}").fetchall()[0][0]


def _set(con: duckdb.DuckDBPyConnection, name: str, value: str | int | float) -> None:
    # names are fixed strings in this module; the value is bound, never formatted into SQL
    con.execute(f"set variable {name} = ?", [value]).fetchall()


def connect(path: str | Path = ":memory:", memory_limit: str = "2GB") -> duckdb.DuckDBPyConnection:
    """Open the warehouse. A file database gets a memory cap and a spill folder beside it, so
    the 32M-row ratings steps run on a laptop instead of failing with out-of-memory."""
    con = duckdb.connect(str(path))
    if str(path) != ":memory:":
        spill = Path(path).with_suffix(".tmp")
        con.execute("set memory_limit = ?", [memory_limit]).fetchall()
        con.execute("set temp_directory = ?", [str(spill)]).fetchall()
        con.execute("set preserve_insertion_order = false").fetchall()
    run_sql_file(con, SQL_DIR / "raw" / "00_create_raw.sql")
    return con


def load_movies(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    """Full refresh of raw_movies from the landed parquet; returns its row count."""
    _set(con, "movies_path", str(parquet_path))
    run_sql_file(con, SQL_DIR / "raw" / "load_movies.sql")
    return _count(con, "raw_movies")


def load_ratings(con: duckdb.DuckDBPyConnection, ratings_csv: Path, links_csv: Path) -> int:
    """Full refresh of raw_ratings and raw_links; returns the raw_ratings row count."""
    _set(con, "ratings_path", str(ratings_csv))
    _set(con, "links_path", str(links_csv))
    run_sql_file(con, SQL_DIR / "raw" / "load_ratings.sql")
    return _count(con, "raw_ratings")


def build_staging(con: duckdb.DuckDBPyConnection, en_min_votes: int) -> None:
    _set(con, "en_min_votes", int(en_min_votes))
    for path in sorted((SQL_DIR / "staging").glob("*.sql")):
        run_sql_file(con, path)


def write_clean(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Store the cleaned frame as mart_movies_clean. It must hold exactly the staged films."""
    staged = [r[0] for r in con.execute("select movie_id from stg_movies").fetchall()]
    if len(df) != len(staged):
        raise ValueError(f"cleaned frame has {len(df)} rows, stg_movies has {len(staged)} rows")
    if set(df["movie_id"].tolist()) != set(staged):
        raise ValueError("cleaned frame movie_id values differ from stg_movies")
    con.register("incoming", df)
    try:
        run_sql_file(con, SQL_DIR / "marts" / "load_movies_clean.sql")
    finally:
        con.unregister("incoming")
    return _count(con, "mart_movies_clean")


def build_marts(
    con: duckdb.DuckDBPyConnection,
    test_months: int,
    val_months: int,
    cf_user_mod: int,
    like_rating: float,
) -> None:
    """Numbered mart files, in order. Needs mart_movies_clean (write_clean) to exist."""
    _set(con, "like_rating", float(like_rating))
    _set(con, "test_months", int(test_months))
    _set(con, "val_months", int(val_months))
    _set(con, "cf_user_mod", int(cf_user_mod))
    for path in sorted((SQL_DIR / "marts").glob("[0-9]*.sql")):
        run_sql_file(con, path)


def snapshot(con: duckdb.DuckDBPyConnection, table: str, n: int = 5) -> dict:
    """Schema, row count and first n rows, for the results page."""
    names = {
        r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()
    }
    if table not in names:
        raise ValueError(f"unknown table {table!r}")
    cols = con.execute(f"describe {table}").fetchall()
    sample = con.execute(f"select * from {table} order by all limit {int(n)}").fetchall()
    return {
        "table": table,
        "row_count": _count(con, table),
        "columns": [[c[0], c[1]] for c in cols],
        "sample": [
            [None if v is None else v if isinstance(v, int | float) else str(v) for v in row]
            for row in sample
        ],
    }
