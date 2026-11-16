"""The site's API on a real Postgres database: entry, check-a-day, scoreboard, outlook, data."""

from datetime import date

import pandas as pd
import pytest
from conftest import TEST_URL, fresh_db
from fastapi.testclient import TestClient

from weatherwise import site, warehouse

TODAY = date(2026, 11, 14)


def log_row(kind, issued, day, lead, variable, pred, lo, hi, published) -> dict:
    return {
        "city": "torrance",
        "kind": kind,
        "issued_on": pd.Timestamp(issued),
        "date": pd.Timestamp(day),
        "variable": variable,
        "lead_days": lead,
        "pred_c": pred,
        "lo_c": lo,
        "hi_c": hi,
        "published_c": published,
        "method": "drift",
        "logged_at": pd.Timestamp("2026-11-14 08:00"),
    }


@pytest.fixture
def client(tmp_path):
    con = fresh_db()
    rows = [
        log_row("hindcast", "2026-11-12", "2026-11-13", 1, "tmax", 25.0, 23.0, 27.0, 24.0),
        log_row("hindcast", "2026-11-12", "2026-11-13", 1, "tmin", 14.0, 12.0, 16.0, 13.0),
        log_row("live", "2026-11-14", "2026-11-15", 1, "tmax", 22.0, 20.0, 24.0, 21.5),
        log_row("live", "2026-11-14", "2026-11-15", 1, "tmin", 12.0, 10.0, 14.0, 11.5),
        log_row("live", "2026-11-13", "2026-11-15", 2, "tmax", 99.0, 98.0, 100.0, 21.0),
    ]
    warehouse.load(con, "forecast_log", pd.DataFrame(rows))
    warehouse.build_models(con)
    con.close()
    app = site.create_app(TEST_URL, data_dir=tmp_path, today=lambda city: TODAY)
    with TestClient(app) as c:
        yield c


def test_home_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "weatherwise" in r.text.lower()


def test_cities_lists_torrance_in_fahrenheit(client):
    cities = {c["name"]: c for c in client.get("/api/cities").json()}
    assert cities["torrance"]["unit"] == "F"
    assert cities["torrance"]["has_forecast"] is True
    assert cities["bengaluru"]["has_forecast"] is False


def test_entering_a_day_in_fahrenheit_returns_the_comparison(client):
    """Fails if the entry is not converted, not stored, or compared with the wrong forecast.

    77 F = 25 C against a forecast of 25.0 -> error 0.0, inside. Published 24.0 -> error -1.0.
    """
    body = {"city": "torrance", "date": "2026-11-13", "tmax": 77, "tmin": 59, "unit": "F"}
    r = client.post("/api/observations", json=body)
    assert r.status_code == 200, r.text
    check = {(c["variable"], c["lead_days"]): c for c in r.json()["checks"]}
    tmax = check[("tmax", 1)]
    assert (tmax["observed_c"], tmax["our_error_c"], tmax["published_error_c"]) == (25.0, 0.0, -1.0)
    assert tmax["inside_range"] is True
    assert check[("tmin", 1)]["our_error_c"] == -1.0  # forecast 14.0, saw 15.0
    listed = client.get("/api/observations", params={"city": "torrance"}).json()
    assert [(o["date"], o["tmax_c"], o["tmin_c"]) for o in listed] == [("2026-11-13", 25.0, 15.0)]
    score = client.get("/api/scoreboard", params={"city": "torrance"}).json()
    assert [(s["variable"], s["n_checks"], s["our_mae_c"]) for s in score] == [
        ("tmax", 1, 0.0),
        ("tmin", 1, 1.0),
    ]


def test_bad_entry_is_refused_with_a_readable_reason(client):
    """Fails if a future date is stored or the user gets a stack trace instead of a reason."""
    body = {"city": "torrance", "date": "2026-11-20", "tmax": 77, "unit": "F"}
    r = client.post("/api/observations", json=body)
    assert r.status_code == 400
    assert "future" in r.json()["detail"]
    assert client.get("/api/observations", params={"city": "torrance"}).json() == []
    r = client.post("/api/observations", json={**body, "city": "atlantis", "date": "2026-11-13"})
    assert r.status_code == 404


def test_deleting_an_entry_removes_it(client):
    body = {"city": "torrance", "date": "2026-11-13", "tmax": 25, "unit": "C"}
    client.post("/api/observations", json=body)
    r = client.delete("/api/observations", params={"city": "torrance", "date": "2026-11-13"})
    assert r.status_code == 200
    assert client.get("/api/observations", params={"city": "torrance"}).json() == []


def test_outlook_is_the_latest_live_forecast_only(client):
    """Fails if yesterday's forecast or a hindcast is shown as today's outlook."""
    out = client.get("/api/outlook", params={"city": "torrance"}).json()
    assert out["issued_on"] == "2026-11-14"
    assert [(d["date"], d["lead_days"]) for d in out["days"]] == [("2026-11-15", 1)]
    assert out["days"][0]["tmax"] == {
        "pred_c": 22.0,
        "lo_c": 20.0,
        "hi_c": 24.0,
        "published_c": 21.5,
        "method": "drift",
    }


def test_entries_survive_a_database_rebuild(client, tmp_path):
    """Fails if the site does not write the backup file a fresh database is restored from."""
    body = {"city": "torrance", "date": "2026-11-13", "tmax": 25, "unit": "C"}
    client.post("/api/observations", json=body)
    fresh = fresh_db()
    warehouse.restore(fresh, tmp_path)
    assert fresh.execute("select tmax_c from raw_user_observation").fetchall() == [(25.0,)]


def test_data_page_lists_tables_with_row_counts(client):
    tables = {t["table"]: t for t in client.get("/api/tables").json()}
    assert tables["log_forecast"]["row_count"] == 5
    assert "raw_user_observation" in tables
