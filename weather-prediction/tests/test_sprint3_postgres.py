"""Sprint 03: behavior that exists because the warehouse is Postgres (migrations, transactions,
checksums) and the three mutants that survived sprint 02."""

from datetime import date

import numpy as np
import pandas as pd
import psycopg
import pytest
from conftest import fresh_db

from weatherwise import deep, observations, warehouse


def actual(rows) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": "t",
            "date": [pd.Timestamp(d) for d, _, _ in rows],
            "tmax_c": [mx for _, mx, _ in rows],
            "tmin_c": [mn for _, _, mn in rows],
            "precip_mm": 0.0,
        }
    )


@pytest.fixture
def con():
    c = fresh_db()
    yield c
    c.close()


def test_migrations_apply_once(con):
    """Fails if a second migrate run re-applies files or records them twice."""
    before = con.execute("select count(*) from schema_migration").fetchall()
    assert before[0][0] >= 1
    assert warehouse.migrate(con) == []
    assert con.execute("select count(*) from schema_migration").fetchall() == before


def test_a_failing_migration_leaves_nothing_behind(con, tmp_path):
    """Fails if half a migration stays applied: the table created before the error must be
    gone and the file must not be recorded as done."""
    (tmp_path / "900_broken.sql").write_text(
        "create table zz_half (a integer);\nselect 1 / 0;\n", encoding="utf-8"
    )
    with pytest.raises(psycopg.Error):
        warehouse.migrate(con, tmp_path)
    assert con.execute("select to_regclass('zz_half')").fetchall() == [(None,)]
    done = con.execute("select count(*) from schema_migration where name like '900%'").fetchall()
    assert done == [(0,)]


def test_reset_refuses_a_database_that_is_not_for_tests():
    """Fails if the test helper could ever empty the real warehouse."""
    with pytest.raises(RuntimeError, match="_test"):
        warehouse.assert_test_database("weatherwise")
    warehouse.assert_test_database("weatherwise_test")


def test_checksum_is_stable_on_reload_and_moves_when_a_value_changes(con):
    """Fails if a rerun changes the stored data, or the checksum cannot see a changed value."""
    df = actual([("2025-01-01", 29.0, 19.0), ("2025-01-02", 28.0, 18.0)])
    warehouse.load(con, "actual_daily", df)
    first = warehouse.checksum(con)["raw_actual_daily"]
    warehouse.load(con, "actual_daily", df)
    assert warehouse.checksum(con)["raw_actual_daily"] == first
    assert first[0] == 2
    df.loc[0, "tmax_c"] = 29.5
    warehouse.load(con, "actual_daily", df)
    assert warehouse.checksum(con)["raw_actual_daily"] != first


def test_a_bad_batch_changes_nothing(con):
    """Fails if a batch with a duplicate key is partly applied: the load is one transaction,
    so the new 3 Jan row must not appear and 1 Jan must keep its old value."""
    warehouse.load(con, "actual_daily", actual([("2025-01-01", 29.0, 19.0)]))
    bad = actual(
        [("2025-01-03", 31.0, 21.0), ("2025-01-01", 35.0, 19.0), ("2025-01-01", 36.0, 19.0)]
    )
    with pytest.raises(psycopg.Error):
        warehouse.load(con, "actual_daily", bad)
    rows = con.execute("select date, tmax_c from raw_actual_daily order by date").fetchall()
    assert rows == [(date(2025, 1, 1), 29.0)]


def test_a_reading_above_the_range_is_outside(con):
    """Fails if only the lower edge of the likely range is checked (sprint-02 survivor).
    Forecast 25 with range 23-27; the user saw 28.5 -> outside."""
    row = {
        "city": "t",
        "kind": "live",
        "issued_on": pd.Timestamp("2026-11-13"),
        "date": pd.Timestamp("2026-11-14"),
        "variable": "tmax",
        "lead_days": 1,
        "pred_c": 25.0,
        "lo_c": 23.0,
        "hi_c": 27.0,
        "published_c": 24.0,
        "method": "raw",
        "logged_at": pd.Timestamp("2026-11-14 08:00"),
    }
    warehouse.load(con, "forecast_log", pd.DataFrame([row]))
    observations.save(con, "t", date(2026, 11, 14), 28.5, None, "C", today=date(2026, 11, 14))
    warehouse.build_models(con)
    got = con.execute("select our_error_c, inside_range from mart_verification").fetchall()
    assert got == [(-3.5, False)]


def test_lstm_keeps_its_best_epoch_not_its_last(con):
    """Fails if early stopping forgets to restore the best weights (sprint-02 survivor): the
    network's validation loss after fit must equal the lowest loss it reached, while the last
    epoch it ran was worse."""
    rng = np.random.default_rng(0)
    x = np.zeros(600)
    for i in range(1, 600):
        x[i] = 0.8 * x[i - 1] + rng.normal(0, 1.0)
    anom = pd.Series(x, index=pd.date_range("2015-01-01", periods=600, freq="D"))
    net = deep.AnomalyLSTM(lookback=14, horizon=3, hidden=8, epochs=40, lr=0.05, patience=3, seed=0)
    net.fit(anom)
    assert net.val_history[-1] > min(net.val_history)  # it did stop on a worse epoch
    assert net.val_loss == pytest.approx(min(net.val_history), abs=1e-6)
