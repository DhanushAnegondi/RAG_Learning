"""Open-Meteo boundary: HTTP with bounded retries, and payload -> typed DataFrames.

Sources (no API key):
- archive-api: ERA5 reanalysis daily values, used as "what actually happened".
- previous-runs-api: hourly forecasts as issued N days before (previous_dayN), used as
  "what was predicted".
- api (forecast): the live 16-day forecast.
"""

import time
from collections.abc import Callable, Iterable

import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_VARS = {
    "temperature_2m_max": "tmax_c",
    "temperature_2m_min": "tmin_c",
    "precipitation_sum": "precip_mm",
}


class IngestError(Exception):
    """A source could not be fetched or returned an unusable payload."""


def fetch_json(
    session: requests.Session,
    url: str,
    params: dict,
    *,
    retries: int = 3,
    timeout: float = 60,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """GET JSON. Retries network errors and 5xx/429 with backoff; 4xx and error bodies fail fast."""
    last = "no attempt"
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            transient = resp.status_code >= 500 or resp.status_code == 429
            try:
                body = resp.json()
            except requests.exceptions.JSONDecodeError:
                body = {"reason": "response body is not JSON"}
                if not transient:
                    raise IngestError(f"{url} HTTP {resp.status_code}: not JSON") from None
            if resp.status_code == 200 and not body.get("error"):
                return body
            last = f"HTTP {resp.status_code}: {body.get('reason', body)}"
            if not transient:
                raise IngestError(f"{url} {last}")
        if attempt < retries - 1:
            sleep(2**attempt)
    raise IngestError(f"{url} failed after {retries} attempts: {last}")


def parse_daily(payload: dict, city: str) -> pd.DataFrame:
    block = payload.get("daily")
    if not block or "time" not in block:
        raise IngestError("payload has no daily block")
    df = pd.DataFrame({"date": pd.to_datetime(block["time"])})
    for src, dst in DAILY_VARS.items():
        df[dst] = pd.to_numeric(pd.Series(block.get(src, [None] * len(df))), errors="coerce")
    df.insert(0, "city", city)
    return df[["city", "date", "tmax_c", "tmin_c", "precip_mm"]]


def parse_previous_runs(
    payload: dict, city: str, leads: Iterable[int] = range(1, 8)
) -> pd.DataFrame:
    block = payload.get("hourly")
    if not block or "time" not in block:
        raise IngestError("payload has no hourly block")
    ts = pd.to_datetime(block["time"])
    parts = []
    for lead in leads:
        col = f"temperature_2m_previous_day{lead}"
        if col not in block:
            raise IngestError(f"payload is missing {col}")
        parts.append(
            pd.DataFrame(
                {"ts_local": ts, "lead_days": lead, "temp_c": pd.to_numeric(pd.Series(block[col]))}
            )
        )
    df = pd.concat(parts, ignore_index=True).dropna(subset=["temp_c"])
    df.insert(0, "city", city)
    return df[["city", "ts_local", "lead_days", "temp_c"]].reset_index(drop=True)


def _loc(city) -> dict:
    return {"latitude": city.latitude, "longitude": city.longitude, "timezone": city.timezone}


def fetch_actuals(session, city, start: str, end: str) -> pd.DataFrame:
    params = {**_loc(city), "start_date": start, "end_date": end, "daily": ",".join(DAILY_VARS)}
    return parse_daily(fetch_json(session, ARCHIVE_URL, params), city.name)


def fetch_published(session, city, start: str, end: str, leads=range(1, 8)) -> pd.DataFrame:
    hourly = ",".join(f"temperature_2m_previous_day{n}" for n in leads)
    params = {**_loc(city), "start_date": start, "end_date": end, "hourly": hourly}
    return parse_previous_runs(fetch_json(session, PREVIOUS_RUNS_URL, params), city.name, leads)


def fetch_live_forecast(session, city, days: int = 16) -> pd.DataFrame:
    params = {**_loc(city), "forecast_days": days, "daily": ",".join(DAILY_VARS)}
    return parse_daily(fetch_json(session, FORECAST_URL, params), city.name)
