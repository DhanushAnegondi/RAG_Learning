"""The assistant's tools: fixed, typed, read-only queries plus two preference tools.

Each data tool is one SQL file in sql/agent/ run as the role `weatherwise_reader` (select on a
few tables, nothing else) with a statement timeout. There is no tool that takes SQL.

run_tool is the only way a tool runs. It validates arguments, logs the call in
agent.tool_call, retries a timeout or a lost connection twice, and returns a stored result
instead of running again when the same call id has already finished (resume after a crash).
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from weatherwise import warehouse
from weatherwise.config import CITIES

SQL = warehouse.SQL_DIR / "agent"
RETRIES = 2  # after the first attempt
MAX_ROWS = 60
PREFS = "prefs"  # store namespace: (PREFS, user_id)


@dataclass
class Context:
    """What a tool may touch: the pool (queries run as the reader role), the preference store
    and the user it is acting for."""

    pool: Any
    store: Any
    user_id: str = "local"
    timeout_s: float = 10.0

    def read(self, sql: str, params: dict | None = None) -> list[dict]:
        """Run one query as weatherwise_reader. The role and the timeout last for this
        transaction only, so the pooled connection goes back unchanged."""
        with self.pool.connection() as con, con.transaction():
            con.execute("set local role weatherwise_reader")
            con.execute("set local transaction_read_only = on")
            ms = f"{int(self.timeout_s * 1000)}ms"
            con.execute("select set_config('statement_timeout', %s, true)", [ms])
            return con.execute(sql, params).fetchall()


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class CityArgs(Args):
    city: str = Field(description="City key in lower case, for example torrance.", max_length=40)

    @field_validator("city")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.strip().lower()


class OutlookArgs(CityArgs):
    days: int = Field(7, ge=1, le=30, description="How many days ahead to return, 1 to 30.")


class ErrorByLeadArgs(CityArgs):
    variable: Literal["tmax", "tmin"] = Field(description="tmax = daily high, tmin = daily low.")


class CheckDayArgs(CityArgs):
    day: date = Field(description="The day to check, YYYY-MM-DD.")


class RememberArgs(Args):
    key: Literal["units", "home_city", "hot_day_threshold", "cold_night_threshold"]
    value: str = Field(
        max_length=40,
        description="units: C or F. home_city: a city key. A threshold: a number and its unit, "
        "for example 85 F.",
    )

    @model_validator(mode="after")
    def check(self):
        v = self.value.strip()
        if self.key == "units":
            if v.upper() not in ("C", "F"):
                raise ValueError("units must be C or F")
            self.value = v.upper()
        elif self.key == "home_city":
            if v.lower() not in CITIES:
                raise ValueError(f"home_city must be one of {sorted(CITIES)}")
            self.value = v.lower()
        else:
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*°?\s*([CcFf])", v)
            if not m:
                raise ValueError("a threshold needs a number and a unit, for example 85 F")
            n, unit = float(m.group(1)), m.group(2).upper()
            c = n if unit == "C" else (n - 32) / 1.8
            if not -60 <= c <= 60:
                raise ValueError("a threshold must be between -60 and 60 C")
            # the user's own number first, unchanged; the other unit beside it
            other = f"{round(c * 1.8 + 32, 1)} F" if unit == "C" else f"{round(c, 1)} C"
            self.value = f"{n:g} {unit} ({other})"
        return self


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[Args]
    run: Callable[[Context, Any], list[dict]]
    temps: tuple[str, ...] = ()  # columns that are temperatures: F = C * 1.8 + 32
    gaps: tuple[str, ...] = ()  # columns that are differences: F = C * 1.8
    empty: str = "no rows"
    facts: tuple[str, ...] = ()  # fixed context returned with the rows, quotable as-is


def sql_tool(name: str) -> Callable[[Context, Args], list[dict]]:
    text = (SQL / f"{name}.sql").read_text(encoding="utf-8")
    return lambda ctx, args: ctx.read(text, args.model_dump())


def remember(ctx: Context, args: RememberArgs) -> list[dict]:
    ctx.store.put((PREFS, ctx.user_id), args.key, {"value": args.value})
    return [{"key": args.key, "value": args.value}]


def preferences(store, user_id: str) -> dict[str, str]:
    items = store.search((PREFS, user_id), limit=20)
    return {i.key: i.value["value"] for i in sorted(items, key=lambda i: i.key)}


def recall(ctx: Context, args: NoArgs) -> list[dict]:
    return [{"key": k, "value": v} for k, v in preferences(ctx.store, ctx.user_id).items()]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "get_outlook",
            "The newest forecast this project issued for a city: one row per day with the "
            "forecast high and low, the likely range for each (low end, high end) and the "
            "published forecast where one exists (days 1-7). Days 8-30 are a seasonal "
            "expectation, not a day-by-day forecast.",
            OutlookArgs,
            sql_tool("get_outlook"),
            temps=(
                "high_c",
                "high_low_end_c",
                "high_high_end_c",
                "published_high_c",
                "low_c",
                "low_low_end_c",
                "low_high_end_c",
                "published_low_c",
            ),
            empty="no rows: no forecast has been issued for this city yet",
            facts=(
                "The likely range aims to hold the real value on 80 percent of days "
                "(8 days in 10).",
                "Days 1 to 7 are published forecasts corrected by this project. Days 8 to 30 "
                "are the seasonal normal adjusted for recent days, not a day-by-day forecast.",
            ),
        ),
        Tool(
            "get_forecast_error_by_lead",
            "Track record by days ahead (1-7) for the daily high or low: how far off the "
            "published forecast has been over the stored history (average miss, bias, share "
            "of days with a large miss, worst miss), and this project's average miss and "
            "range hit rate on the held-out year its models never saw.",
            ErrorByLeadArgs,
            sql_tool("get_forecast_error_by_lead"),
            gaps=(
                "published_bias_c",
                "published_avg_miss_c",
                "published_worst_miss_c",
                "weatherwise_avg_miss_last_12_months_c",
            ),
            empty="no rows: no forecast history is loaded for this city",
            facts=(
                "Two different periods are in each row. Columns starting with published_ cover "
                "the whole stored history of the published forecast: n_days days, not the last "
                "12 months.",
                "Columns starting with weatherwise_ cover only the last 12 months, which this "
                "project's models never saw.",
                "published_pct_days_off_3c_or_more counts days off by 3 C (5.4 F) or more.",
                "published_bias above 0 means the published forecast ran too warm, below 0 too "
                "cool.",
            ),
        ),
        Tool(
            "check_day",
            "For a day the user typed a reading for: every forecast made for that day (1 to 30 "
            "days before) against the reading. error = forecast minus reading.",
            CheckDayArgs,
            sql_tool("check_day"),
            temps=(
                "observed_c",
                "weatherwise_c",
                "range_low_end_c",
                "range_high_end_c",
                "published_c",
            ),
            gaps=("weatherwise_error_c", "published_error_c"),
            empty="no rows: the user has not entered a reading for that day, or no forecast "
            "was logged for it",
        ),
        Tool(
            "get_scoreboard",
            "Score on the user's own readings by days ahead: number of readings, this "
            "project's average miss, the published forecast's average miss, how often the "
            "reading fell inside the likely range, and reading minus grid data.",
            CityArgs,
            sql_tool("get_scoreboard"),
            gaps=(
                "weatherwise_avg_miss_c",
                "published_avg_miss_c",
                "weatherwise_avg_miss_same_days_c",
                "reading_minus_grid_c",
            ),
            empty="no rows: the user has not entered any readings yet",
        ),
        Tool(
            "get_data_health",
            "What data arrived per source, how many days survived cleaning, how many were "
            "rejected or are missing, and the day the forecast was last run.",
            CityArgs,
            sql_tool("get_data_health"),
            empty="no rows: nothing is loaded for this city",
        ),
        Tool(
            "remember_preference",
            "Save a lasting preference the user states: units, home city, or a temperature "
            "threshold they care about. Use only when the user asks for it or states it.",
            RememberArgs,
            remember,
        ),
        Tool(
            "recall_preferences",
            "List the preferences saved for this user.",
            NoArgs,
            recall,
        ),
    )
}


def schemas(tools: dict[str, Tool]) -> list[dict]:
    """Tool definitions in the Messages API shape."""
    out = []
    for t in tools.values():
        schema = t.args.model_json_schema()
        schema.pop("title", None)
        out.append({"name": t.name, "description": t.description, "input_schema": schema})
    return out


def clean(row: dict, tool: Tool) -> dict:
    """JSON-safe row. Every Celsius column listed on the tool gets a Fahrenheit twin, so the
    model never converts units itself."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime | date):
            v = v.isoformat()
        elif isinstance(v, Decimal):
            v = float(v)
        out[k] = v
        if v is not None and k in tool.temps:
            out[k[:-2] + "_f"] = round(v * 1.8 + 32, 1)
        elif v is not None and k in tool.gaps:
            out[k[:-2] + "_f"] = round(v * 1.8, 1)
    return out


def problems(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'value'}: {e['msg']}" for e in exc.errors()
    )


def _log(ctx: Context, sql: str, params: list) -> list[dict]:
    with ctx.pool.connection() as con:
        cur = con.execute(sql, params)
        return cur.fetchall() if cur.description else []


def run_tool(
    ctx: Context,
    thread_id: str,
    call: dict,
    tools: dict[str, Tool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Run one tool call and return its result as a dict (status ok | error | timeout)."""
    tools = TOOLS if tools is None else tools
    name, raw = call["name"], call.get("args") or {}
    call_id = f"{thread_id}:{call['id']}"
    done = _log(
        ctx, "select status, tool, args, result from agent.tool_call where call_id = %s", [call_id]
    )
    if done and done[0]["status"] == "ok":
        if (done[0]["tool"], done[0]["args"]) != (name, raw):  # an id reused for another call
            return {
                "tool": name,
                "status": "error",
                "error": f"call id {call['id']!r} was already used for a different call",
                "replayed": False,
            }
        return {**done[0]["result"], "replayed": True}

    refusal = None
    if name not in tools:
        refusal = f"unknown tool {name!r}; known: {sorted(tools)}"
    else:
        try:
            args = tools[name].args.model_validate(raw)
        except ValidationError as exc:
            refusal = f"bad arguments: {problems(exc)}"
    _log(
        ctx,
        "insert into agent.tool_call (call_id, thread_id, tool, args, status, error) "
        "values (%s, %s, %s, %s, %s, %s) "
        "on conflict (call_id) do update set status = excluded.status, error = excluded.error, "
        "tool = excluded.tool, args = excluded.args",
        [call_id, thread_id, name, Jsonb(raw), "error" if refusal else "running", refusal],
    )
    if refusal:
        return {"tool": name, "status": "error", "error": refusal, "replayed": False}

    tool, started = tools[name], time.perf_counter()
    for attempt in range(RETRIES + 1):
        _log(
            ctx, "update agent.tool_call set attempts = attempts + 1 where call_id = %s", [call_id]
        )
        try:
            rows = [clean(r, tool) for r in tool.run(ctx, args)]
            break
        except psycopg.errors.QueryCanceled as exc:
            status, failure = "timeout", exc
        except psycopg.OperationalError as exc:
            status, failure = "error", exc
        except Exception as exc:  # a permission, SQL or code error will not fix itself
            status, failure = "error", exc
            attempt = RETRIES
        if attempt == RETRIES:
            reason = f"{type(failure).__name__}: {(str(failure).splitlines() or [''])[0]}"
            _log(
                ctx,
                "update agent.tool_call set status = %s, error = %s, ms = %s, "
                "finished_at = localtimestamp where call_id = %s",
                [status, reason, int((time.perf_counter() - started) * 1000), call_id],
            )
            return {
                "tool": name,
                "status": status,
                "error": "data unavailable: the database could not be read "
                f"({type(failure).__name__}). Do not estimate; tell the user the data could "
                "not be read.",
                "replayed": False,
            }
        sleep(0.5 * 2**attempt)

    result = {"tool": name, "status": "ok", "row_count": len(rows), "rows": rows[:MAX_ROWS]}
    if tool.facts:
        result["facts"] = list(tool.facts)
    if not rows:
        result["note"] = tool.empty
    elif len(rows) > MAX_ROWS:
        result["note"] = f"first {MAX_ROWS} of {len(rows)} rows"
    _log(
        ctx,
        "update agent.tool_call set status = 'ok', row_count = %s, ms = %s, result = %s, "
        "error = null, finished_at = localtimestamp where call_id = %s",
        [len(rows), int((time.perf_counter() - started) * 1000), Jsonb(result), call_id],
    )
    return {**result, "replayed": False}
