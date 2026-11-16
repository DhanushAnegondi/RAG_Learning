"""Ingest: Open-Meteo payload parsing and the HTTP boundary. Offline: fake session, no network."""

import pandas as pd
import pytest

from weatherwise.ingest import IngestError, fetch_json, parse_daily, parse_previous_runs


class FakeResponse:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict:
        return self._body


class FakeSession:
    """Returns queued responses (or raises queued exceptions) in order; records calls."""

    def __init__(self, queue: list) -> None:
        self.queue = list(queue)
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


DAILY_PAYLOAD = {
    "timezone": "Asia/Kolkata",
    "daily": {
        "time": ["2025-03-01", "2025-03-02"],
        "temperature_2m_max": [31.4, None],
        "temperature_2m_min": [19.0, 18.5],
        "precipitation_sum": [0.0, 2.5],
    },
}


def test_parse_daily_keeps_rows_and_nulls_as_nan():
    """Fails if a null max temperature is dropped or turned into 0 instead of NaN."""
    df = parse_daily(DAILY_PAYLOAD, city="testville")
    assert list(df.columns) == ["city", "date", "tmax_c", "tmin_c", "precip_mm"]
    assert len(df) == 2
    assert df.loc[0, "tmax_c"] == 31.4
    assert pd.isna(df.loc[1, "tmax_c"])
    assert df.loc[1, "precip_mm"] == 2.5
    assert df["date"].tolist() == [pd.Timestamp("2025-03-01"), pd.Timestamp("2025-03-02")]
    assert (df["city"] == "testville").all()


def test_parse_previous_runs_goes_wide_to_long_by_lead_and_drops_nulls():
    """Fails if lead numbers are mislabelled (day1 must be lead 1) or null hours are kept."""
    payload = {
        "hourly": {
            "time": ["2025-03-01T00:00", "2025-03-01T01:00"],
            "temperature_2m_previous_day1": [20.0, 21.0],
            "temperature_2m_previous_day3": [22.0, None],
        }
    }
    df = parse_previous_runs(payload, city="testville", leads=[1, 3])
    assert list(df.columns) == ["city", "model", "ts_local", "lead_days", "temp_c"]
    assert (df["model"] == "best_match").all()
    got = sorted(zip(df["lead_days"], df["ts_local"].dt.hour, df["temp_c"], strict=True))
    assert got == [(1, 0, 20.0), (1, 1, 21.0), (3, 0, 22.0)]


def test_parse_previous_runs_missing_lead_column_raises():
    """Fails if a lead the caller asked for silently disappears."""
    payload = {"hourly": {"time": ["2025-03-01T00:00"], "temperature_2m_previous_day1": [20.0]}}
    with pytest.raises(IngestError, match="previous_day2"):
        parse_previous_runs(payload, city="x", leads=[1, 2])


def test_parse_daily_without_daily_block_raises():
    """Fails if a malformed payload produces an empty frame instead of an error."""
    with pytest.raises(IngestError):
        parse_daily({"hourly": {}}, city="x")


def test_fetch_json_retries_transient_then_succeeds():
    """Fails if a 503 is not retried or the timeout is not passed to the session."""
    session = FakeSession([FakeResponse(503, {}), FakeResponse(200, {"ok": 1})])
    sleeps: list[float] = []
    body = fetch_json(session, "https://x", {"a": 1}, retries=3, timeout=7, sleep=sleeps.append)
    assert body == {"ok": 1}
    assert len(session.calls) == 2
    assert session.calls[0]["timeout"] == 7
    assert len(sleeps) == 1


def test_fetch_json_does_not_retry_client_error():
    """Fails if a 400 (bad request, will never succeed) is retried."""
    session = FakeSession([FakeResponse(400, {"error": True, "reason": "bad var"})])
    with pytest.raises(IngestError, match="bad var"):
        fetch_json(session, "https://x", {}, retries=3, sleep=lambda s: None)
    assert len(session.calls) == 1


def test_fetch_json_gives_up_after_retries():
    """Fails if retries are unbounded or the final error is swallowed."""
    import requests

    session = FakeSession([requests.ConnectionError("down")] * 3)
    with pytest.raises(IngestError):
        fetch_json(session, "https://x", {}, retries=3, sleep=lambda s: None)
    assert len(session.calls) == 3


def test_fetch_json_error_body_with_200_raises():
    """Fails if Open-Meteo's {"error": true} body is treated as data."""
    session = FakeSession([FakeResponse(200, {"error": True, "reason": "nope"})])
    with pytest.raises(IngestError, match="nope"):
        fetch_json(session, "https://x", {}, sleep=lambda s: None)
