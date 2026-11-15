"""Postgres warehouse. All SQL lives in sql/<folder>/*.sql; this module only runs it.

Connections are autocommit; anything that must be all-or-nothing (a load, a migration, a
rebuild of the models) opens its own transaction.
"""

from pathlib import Path

import pandas as pd
import psycopg

from weatherwise.config import database_url

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
TABLE = {  # loader name -> table; also the identifier allowlist
    "actual_daily": "raw_actual_daily",
    "published_hourly": "raw_published_hourly",
    "live_forecast": "raw_live_forecast",
    "user_observation": "raw_user_observation",
    "forecast_log": "log_forecast",
    "model_eval": "app_model_eval",
    "run": "app_run",
}
LOADABLE = tuple(TABLE)
MIGRATE_LOCK = 7312001  # arbitrary key for pg_advisory_lock
HAS_MODEL = ("published_hourly", "live_forecast")
BACKUPS = {  # what cannot be rebuilt from the APIs: file name -> (loader, query)
    "user_observations.csv": (
        "user_observation",
        "select * from raw_user_observation order by city, date",
    ),
    "forecast_log_live.csv": (
        "forecast_log",
        "select * from log_forecast where kind = 'live' order by city, issued_on, date, variable",
    ),
}


def run_sql_file(con: psycopg.Connection, path: Path, params: dict | None = None) -> None:
    con.execute(path.read_text(encoding="utf-8"), params)


def frame(con: psycopg.Connection, sql: str, params=None) -> pd.DataFrame:
    """Query -> DataFrame (nulls become NaN in numeric columns)."""
    cur = con.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def migrate(con: psycopg.Connection, directory: Path | None = None) -> list[str]:
    """Apply pending sql/migrations files in name order, each in its own transaction.
    Returns the names applied now; a failing file leaves nothing behind."""
    con.execute("select pg_advisory_lock(%s)", [MIGRATE_LOCK])  # one migrator at a time
    try:
        run_sql_file(con, SQL_DIR / "migrations" / "000_schema_migration.sql")
        done = {r[0] for r in con.execute("select name from schema_migration").fetchall()}
        applied = []
        for path in sorted(Path(directory or SQL_DIR / "migrations").glob("*.sql")):
            if path.name in done or path.name.startswith("000_"):
                continue
            with con.transaction():
                run_sql_file(con, path)
                con.execute("insert into schema_migration (name) values (%s)", [path.name])
            applied.append(path.name)
        return applied
    finally:
        con.execute("select pg_advisory_unlock(%s)", [MIGRATE_LOCK])


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection and bring the schema up to date."""
    con = psycopg.connect(url or database_url(), autocommit=True)
    try:
        migrate(con)
    except BaseException:
        con.close()
        raise
    return con


def assert_test_database(name: str) -> None:
    if not name.endswith("_test"):
        raise RuntimeError(f"refusing to empty database {name!r}: its name must end with _test")


def reset(con: psycopg.Connection) -> None:
    """Empty every table. Test databases only."""
    assert_test_database(con.execute("select current_database()").fetchall()[0][0])
    run_sql_file(con, SQL_DIR / "checks" / "reset_test.sql")


def load(con: psycopg.Connection, table: str, df: pd.DataFrame) -> int:
    """Upsert df into the table behind `table`, as one transaction; returns the table's row
    count afterwards. A key repeated inside df raises and nothing is written."""
    if table not in TABLE:
        raise ValueError(f"unknown table {table!r}; expected one of {LOADABLE}")
    if table in HAS_MODEL and "model" not in df.columns:
        df = df.assign(model="best_match")  # the forecast Open-Meteo publishes by default
    target, cols = TABLE[table], list(df.columns)
    if not all(c.isidentifier() for c in cols):
        raise ValueError(f"bad column name in {cols}")
    rows = df.astype(object).where(df.notna(), None).values.tolist()
    with con.transaction():
        con.execute("drop table if exists incoming")
        # same columns, defaults and primary key as the target: a repeated key fails at copy
        like = f"like {target} including defaults including indexes"
        con.execute(f"create temp table incoming ({like}) on commit drop")
        with con.cursor().copy(f"copy incoming ({', '.join(cols)}) from stdin") as copy:
            for row in rows:
                copy.write_row(row)
        run_sql_file(con, SQL_DIR / "raw" / f"load_{table}.sql")
    return con.execute(f"select count(*) from {target}").fetchall()[0][0]


def checksum(con: psycopg.Connection) -> dict[str, tuple[int, int]]:
    """{table: (row count, content digest)} for the fetched tables; equal after a reload."""
    sql = (SQL_DIR / "checks" / "checksum.sql").read_text(encoding="utf-8")
    return {name: (int(n), int(digest)) for name, n, digest in con.execute(sql).fetchall()}


def backup(con: psycopg.Connection, data_dir: str | Path) -> None:
    """Write the user's entries and live forecasts to CSV: they cannot be fetched again."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    for name, (_, query) in BACKUPS.items():
        frame(con, query).to_csv(Path(data_dir) / name, index=False)


def restore(con: psycopg.Connection, data_dir: str | Path) -> None:
    """Load the CSV backups into a (possibly new) database. Safe to repeat."""
    for name, (table, _) in BACKUPS.items():
        path = Path(data_dir) / name
        if path.exists():
            df = pd.read_csv(path)
            if len(df):
                load(con, table, df)


def build_models(con: psycopg.Connection) -> None:
    """Rebuild staging views and marts in one transaction, so readers never see a gap."""
    with con.transaction():
        for stage in ("staging", "marts"):
            for path in sorted((SQL_DIR / stage).glob("*.sql")):
                run_sql_file(con, path)


def snapshot(con: psycopg.Connection, table: str, n: int = 5) -> dict:
    """Schema, row count and first n rows, for the results page and the site."""
    cols = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = current_schema() and table_name = %s order by ordinal_position",
        [table],
    ).fetchall()
    if not cols:
        raise ValueError(f"unknown table {table!r}")
    count = con.execute(f"select count(*) from {table}").fetchall()[0][0]
    order = ", ".join(str(i) for i in range(1, len(cols) + 1))
    sample = con.execute(f"select * from {table} order by {order} limit {int(n)}").fetchall()
    return {
        "table": table,
        "row_count": count,
        "columns": [[c[0], c[1]] for c in cols],
        "sample": [
            [None if v is None else str(v) if not isinstance(v, int | float) else v for v in row]
            for row in sample
        ],
    }
