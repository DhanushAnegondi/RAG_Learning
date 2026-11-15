"""The weatherwise site: a small API over the Postgres warehouse plus the static pages in web/.

Run: make site  (http://localhost:8000). Temperatures cross the API in Celsius; the page
converts for display. Every query is a file in sql/site/.
"""

import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from weatherwise import observations, pipeline, warehouse
from weatherwise.config import CITIES, database_url

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"


class Entry(BaseModel):
    city: str
    date: date
    tmax: float | None = None
    tmin: float | None = None
    unit: str = "C"
    note: str | None = None


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe rows: NaN/NaT become null, dates become ISO strings."""
    out = []
    for row in df.to_dict("records"):
        clean = {}
        for k, v in row.items():
            if v is None or (not isinstance(v, str) and pd.isna(v)):
                clean[k] = None
            elif isinstance(v, pd.Timestamp | datetime):
                clean[k] = v.isoformat()  # dates arrive as date objects, never as timestamps
            elif isinstance(v, date):
                clean[k] = v.isoformat()
            elif hasattr(v, "item"):
                clean[k] = v.item()
            else:
                clean[k] = v
        out.append(clean)
    return out


def query(con, name: str, params: dict | None = None) -> pd.DataFrame:
    sql = (warehouse.SQL_DIR / "site" / f"{name}.sql").read_text(encoding="utf-8")
    return warehouse.frame(con, sql, params)


def create_app(url: str | None = None, data_dir: str | Path | None = None, today=None) -> FastAPI:
    """`today(city) -> date` is injectable so tests do not depend on the clock."""
    url = url or database_url()
    data_dir = Path(data_dir) if data_dir else ROOT / "data"
    today = today or pipeline.city_today
    state = {"refresh": {"running": False, "city": None, "error": None, "finished": None}}
    lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with warehouse.connect(url) as con:  # migrate, restore backups, build the models once
            warehouse.restore(con, data_dir)
            warehouse.build_models(con)
        with ConnectionPool(url, min_size=1, max_size=4, kwargs={"autocommit": True}) as pool:
            state["pool"] = pool
            yield

    app = FastAPI(title="weatherwise", lifespan=lifespan)

    def cur():
        """One pooled connection per request, returned to the pool when the request ends."""
        return state["pool"].connection()

    def city_or_404(name: str):
        if name not in CITIES:
            raise HTTPException(404, f"unknown city {name!r}; known: {sorted(CITIES)}")
        return CITIES[name]

    @app.get("/api/cities")
    def cities() -> list[dict]:
        with cur() as con:
            issued = {r["city"]: r["issued_on"] for r in records(query(con, "forecast_cities"))}
            runs = {r["city"]: r for r in records(query(con, "runs"))}
        return [
            {
                "name": c.name,
                "unit": c.unit,
                "has_forecast": c.name in issued,
                "issued_on": issued.get(c.name),
                "run_utc": runs.get(c.name, {}).get("run_utc"),
                "test_start": runs.get(c.name, {}).get("test_start"),
                "today": today(c).isoformat(),
            }
            for c in CITIES.values()
        ]

    @app.get("/api/outlook")
    def outlook(city: str) -> dict:
        city_or_404(city)
        with cur() as con:
            rows = records(query(con, "outlook", {"city": city}))
        days: dict[str, dict] = {}
        for r in rows:
            day = days.setdefault(r["date"], {"date": r["date"], "lead_days": r["lead_days"]})
            day[r["variable"]] = {
                k: r[k] for k in ("pred_c", "lo_c", "hi_c", "published_c", "method")
            }
        return {"issued_on": rows[0]["issued_on"] if rows else None, "days": list(days.values())}

    def simple(name: str):
        def endpoint(city: str) -> list[dict]:
            city_or_404(city)
            with cur() as con:
                return records(query(con, name, {"city": city}))

        endpoint.__name__ = name
        return endpoint

    for route, name in (
        ("/api/history", "history"),
        ("/api/leaderboard", "leaderboard"),
        ("/api/error-by-lead", "error_by_lead"),
        ("/api/quality", "quality"),
        ("/api/issues", "issues"),
        ("/api/scoreboard", "scoreboard"),
    ):
        app.get(route)(simple(name))

    @app.get("/api/observations")
    def list_observations(city: str) -> list[dict]:
        city_or_404(city)
        with cur() as con:
            return records(query(con, "observations", {"city": city}))

    @app.get("/api/check")
    def check(city: str, date: date) -> dict:
        city_or_404(city)
        with cur() as con:
            return {"checks": records(query(con, "check", {"city": city, "day": date}))}

    @app.post("/api/observations")
    def add_observation(entry: Entry) -> dict:
        city = city_or_404(entry.city)
        with cur() as con:
            try:
                observations.save(
                    con,
                    city.name,
                    entry.date,
                    entry.tmax,
                    entry.tmin,
                    entry.unit,
                    today=today(city),
                    note=entry.note,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            warehouse.backup(con, data_dir)
            params = {"city": city.name, "day": entry.date}
            return {"checks": records(query(con, "check", params))}

    @app.delete("/api/observations")
    def delete_observation(city: str, date: date) -> dict:
        city_or_404(city)
        with cur() as con:
            observations.delete(con, city, date)
            warehouse.backup(con, data_dir)
        return {"deleted": date.isoformat()}

    @app.get("/api/tables")
    def tables() -> list[dict]:
        with cur() as con:
            return [warehouse.snapshot(con, t, n=8) for t in pipeline.TABLES]

    def run_refresh(city) -> None:
        job = state["refresh"]
        try:
            with cur() as con:
                pipeline.refresh(con, city, today(city), data_dir=data_dir)
            job["error"] = None
        except Exception as exc:  # shown to the user on the page; the server keeps running
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            job["running"] = False
            job["finished"] = datetime.now().isoformat(timespec="seconds")

    @app.post("/api/refresh")
    def refresh(city: str) -> dict:
        """Fetch new data and re-forecast in the background (a few minutes)."""
        c = city_or_404(city)
        job = state["refresh"]
        with lock:  # two quick clicks must not start two refreshes
            if job["running"]:
                raise HTTPException(409, f"a refresh for {job['city']} is already running")
            job.update(running=True, city=city, error=None, finished=None)
        threading.Thread(target=run_refresh, args=(c,), daemon=True).start()
        return job

    @app.get("/api/refresh")
    def refresh_status() -> dict:
        return state["refresh"]

    @app.get("/")
    def home() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


def main() -> None:
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
