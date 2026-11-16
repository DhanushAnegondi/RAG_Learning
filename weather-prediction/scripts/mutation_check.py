"""Break the code on purpose; each mutation must make at least one test fail. Restores files.

Run: .venv/Scripts/python scripts/mutation_check.py  (make mutate)
KILLED means pytest exited 1 (a test failed) and names the first failing test. Test files run
in an order that puts the likeliest killers first (test_order); a survivor has faced them all. A crash
(exit 2+, e.g. a syntax error) counts as CRASHED, not as a kill. A mutant of a migration file
only exists once the migration runs, so the test database's schema is dropped before such a
mutant and again after it.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
M = "src/weatherwise/models.py"
P = "src/weatherwise/pipeline.py"
I = "src/weatherwise/ingest.py"  # noqa: E741
R = "src/weatherwise/report.py"
OB = "src/weatherwise/observations.py"
WH = "src/weatherwise/warehouse.py"
S = "src/weatherwise/site.py"
D = "src/weatherwise/deep.py"
AT = "src/weatherwise/agent/tools.py"
AG = "src/weatherwise/agent/grounding.py"
GR = "src/weatherwise/agent/graph.py"
MART = "sql/marts/01_mart_forecast_error.sql"
LEAD = "sql/marts/02_mart_error_by_lead.sql"
MUTATIONS = [  # (file, original, mutant, what it simulates); the full suite runs each time
    (
        MART,
        "long_form.forecast_c - long_form.actual_c as error_c",
        "long_form.actual_c - long_form.forecast_c as error_c",
        "error sign flipped",
    ),
    (
        "sql/staging/stg_published_daily.sql",
        "where by_day.n_hours = 24",
        "where by_day.n_hours > 0",
        "partial days kept",
    ),
    (MART, "inner join actual", "left join actual", "inner join became left join"),
    (
        MART,
        "on published.city = actual.city and published.date = actual.date",
        "on published.date = actual.date",
        "join key loses city",
    ),
    (
        WH,
        'like = f"like {target} including defaults including indexes"',
        'like = f"like {target} including defaults"',
        "duplicate keys in a batch accepted",
    ),
    (
        "sql/raw/load_actual_daily.sql",
        "        tmax_c = excluded.tmax_c,\n",
        "",
        "corrected max not replaced on reload",
    ),
    (
        WH,
        '    with con.transaction():\n        con.execute("drop table if exists incoming")',
        '    if True:\n        con.execute("drop table if exists incoming")',
        "load is not one transaction",
    ),
    (
        WH,
        'if not name.endswith("_test"):',
        "if False:",
        "reset allowed on the real database",
    ),
    (
        WH,
        '        if path.name in done or path.name.startswith("000_"):',
        '        if path.name.startswith("000_"):',
        "migrations re-applied",
    ),
    (
        "sql/checks/checksum.sql",
        "cast(row(city, date, tmax_c, tmin_c, precip_mm) as text)",
        "cast(row(city, date) as text)",
        "checksum blind to values",
    ),
    (
        "sql/migrations/001_tables.sql",
        "primary key (city, model, issued_on, date)",
        "primary key (city, model, date)",
        "live forecast key loses issued_on",
    ),
    (
        "sql/staging/stg_published_daily.sql",
        "group by source.city, source.model, source.lead_days, cast(source.ts_local as date)",
        "group by source.city, source.model, source.lead_days * 0, cast(source.ts_local as date)",
        "leads merged in staging grain",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "    source.tmax_c between -60 and 60\n",
        "    true\n",
        "null or impossible max reaches the marts",
    ),
    (
        LEAD,
        "sqrt(avg(errors.error_c * errors.error_c))",
        "avg(abs(errors.error_c))",
        "rmse computed as mae",
    ),
    (
        LEAD,
        "when abs(errors.error_c) >= 3",
        "when abs(errors.error_c) > 3",
        "share_off_3c boundary",
    ),
    (I, '"lead_days": lead,', '"lead_days": lead + 1,', "lead labelled off by one"),
    (
        I,
        "transient = resp.status_code >= 500 or resp.status_code == 429",
        "transient = resp.status_code >= 500",
        "429 not retried",
    ),
    (
        I,
        "except requests.exceptions.JSONDecodeError:",
        "except ZeroDivisionError:",
        "non-JSON 5xx not retried",
    ),
    (
        I,
        '"timezone": city.timezone',
        '"tz_unused": city.timezone',
        "timezone dropped from requests",
    ),
    (
        M,
        'if maes[best] > maes["raw"] * (1 - self.min_gain):',
        "if False:",
        "selection margin removed",
    ),
    (
        M,
        'return df[df["date"] < test_start], df[df["date"] >= test_start]',
        'return df[df["date"] <= test_start], df[df["date"] >= test_start]',
        "test start date leaks into train",
    ),
    (
        M,
        "for k in range(self.n_folds, 0, -1):",
        "for k in range(self.n_folds * 3, 0, -1):",
        "band built from stale years",
    ),
    (
        M,
        "(min(float(lo), 0.0), max(float(hi), 0.0))",
        "(float(lo), float(hi))",
        "band clamp removed",
    ),
    (
        M,
        "return anom.rolling(window, min_periods=window).mean()",
        "return anom.rolling(window, min_periods=1).mean()",
        "partial anomaly windows",
    ),
    (M, "if age > max_age_days:", "if False:", "stale anomaly accepted"),
    (M, "    if missing:", "    if False:", "missing published days accepted"),
    (
        M,
        'short = out["lead_days"] <= short_leads',
        'short = out["lead_days"] < short_leads',
        "day 7 not corrected",
    ),
    (
        M,
        "base + coef[:horizon] * recent_anomaly",
        "base + np.roll(coef[:horizon], 1) * recent_anomaly",
        "decay coefficient misaligned",
    ),
    (P, "fit_part = actual.iloc[:-365]", "fit_part = actual", "long-range bands in-sample"),
    (
        P,
        "train = actual[actual.index < test_start]",
        "train = actual",
        "long-range fit sees test window",
    ),
    (P, "if start > stop:", "if False:", "inverted range on 1 January"),
    (
        R,
        "f\"{escape(o.read_text(encoding='utf-8'))}</pre></details>\"",
        "f\"{o.read_text(encoding='utf-8')}</pre></details>\"",
        "terminal output not escaped",
    ),
    (R, "reverse=True,", "reverse=False,", "sprints oldest first"),
    # ---- sprint 02 ----
    (
        "sql/migrations/001_tables.sql",
        "primary key (city, model, ts_local, lead_days)",
        "primary key (city, ts_local, lead_days)",
        "weather model drops out of the key",
    ),
    (
        "sql/migrations/001_tables.sql",
        "primary key (city, kind, issued_on, date, variable)",
        "primary key (city, issued_on, date, variable)",
        "hindcast can overwrite a live forecast",
    ),
    (
        "sql/raw/load_forecast_log.sql",
        "    kind = 'hindcast'\n    and city in (",
        "    kind <> 'x'\n    and city in (",
        "replay deletes live forecasts",
    ),
    (MART, "where model = 'best_match'", "where true", "other models leak into published error"),
    (
        "sql/staging/stg_published_daily.sql",
        "where temp_c between -60 and 60",
        "where true",
        "impossible forecast hour kept",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "    and source.tmax_c >= source.tmin_c",
        "",
        "max below min accepted",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "    and source.tmin_c between -60 and 60\n",
        "",
        "impossible min accepted",
    ),
    (
        "sql/marts/03_mart_model_pairs.sql",
        "when published.model = 'gfs_seamless' then published.tmax_c end) as tmax_gfs",
        "when published.model = 'ecmwf_ifs025' then published.tmax_c end) as tmax_gfs",
        "gfs column filled from ecmwf",
    ),
    (
        "sql/marts/04_mart_data_quality.sql",
        "actual_raw.raw_rows - actual_ok.usable_days as rejected_days",
        "0 as rejected_days",
        "rejected days not counted",
    ),
    (
        "sql/marts/05_mart_verification.sql",
        "order by case when log_forecast.kind = 'live' then 0 else 1 end",
        "order by case when log_forecast.kind = 'live' then 1 else 0 end",
        "hindcast preferred over live",
    ),
    (
        "sql/marts/05_mart_verification.sql",
        "ranked.pred_c - observed.observed_c as our_error_c",
        "observed.observed_c - ranked.pred_c as our_error_c",
        "verification error sign flipped",
    ),
    (
        "sql/marts/05_mart_verification.sql",
        "(observed.observed_c between ranked.lo_c and ranked.hi_c) as inside_range",
        "(observed.observed_c >= ranked.lo_c) as inside_range",
        "inside-range ignores the upper edge",
    ),
    (
        "sql/site/outlook.sql",
        "select max(newest.issued_on)",
        "select min(newest.issued_on)",
        "outlook shows the oldest forecast",
    ),
    (OB, "(value - 32) * 5 / 9", "(value - 32) * 9 / 5", "fahrenheit conversion wrong"),
    (OB, "    if day > today:", "    if False:", "future entry accepted"),
    (
        OB,
        "tmax_c is not None and tmin_c is not None and tmax_c < tmin_c",
        "False",
        "high below low accepted",
    ),
    (
        OB,
        "if v is not None and not LIMIT_C[0] <= v <= LIMIT_C[1]:",
        "if False:",
        "impossible entry accepted",
    ),
    (
        WH,
        'df = df.assign(model="best_match")',
        'df = df.assign(model="gfs_seamless")',
        "default model mislabelled",
    ),
    (
        WH,
        "select * from log_forecast where kind = 'live'",
        "select * from log_forecast",
        "backup includes hindcasts",
    ),
    (
        I,
        'block.get(f"{src}_{model}"',
        'block.get(f"{src}_best_match"',
        "every model reads best_match",
    ),
    (M, ".mean().shift(int(lead) + 1)", ".mean().shift(int(lead))", "recent bias peeks one day"),
    (
        M,
        'd["forecast_c"] - d["bias_recent"].fillna(0.0)',
        'd["forecast_c"] + d["bias_recent"].fillna(0.0)',
        "drift adds the bias",
    ),
    (
        M,
        "return lambda d: np.nanmean(_model_matrix(d), axis=1)",
        "return lambda d: np.nan_to_num(_model_matrix(d)).mean(axis=1)",
        "missing model counted as zero",
    ),
    (
        M,
        "keep = ~np.isnan(x).all(axis=0)",
        "keep = np.ones(x.shape[1], dtype=bool)",
        "all-NaN model column kept",
    ),
    (M, ".ffill().shift(lead + 1)", ".ffill().shift(lead)", "adaptive range peeks one day"),
    (
        M,
        'out.loc[g.index, "lo_c"] = pred + np.minimum(edges["lo_c"], 0.0)',
        'out.loc[g.index, "lo_c"] = pred + edges["lo_c"]',
        "adaptive range can exclude the forecast",
    ),
    (
        M,
        'out["pred_c"] = base + coef[:horizon] * recent_anomaly if long_pred is None else long_pred',
        'out["pred_c"] = base + coef[:horizon] * recent_anomaly',
        "long-range override ignored",
    ),
    (
        P,
        'val_mae["decay"] * (1 - min_gain)',
        'val_mae["decay"] * (1 + min_gain)',
        "LSTM wins on a sliver",
    ),
    (
        P,
        "return now.astimezone(ZoneInfo(city.timezone)).date()",
        "return now.date()",
        "today from UTC, not the city",
    ),
    (
        P,
        'out["date"] - pd.to_timedelta(out["lead_days"], unit="D")',
        'out["date"] + pd.to_timedelta(out["lead_days"], unit="D")',
        "issue day computed forwards",
    ),
    (
        P,
        "train = actual[actual.index < test_start]\n    chosen, resid",
        "train = actual\n    chosen, resid",
        "long-range selection sees test window",
    ),
    (
        S,
        "raise HTTPException(400, str(exc)) from None",
        'return {"checks": []}',
        "bad entry reported as success",
    ),
    (D, "self.net.load_state_dict(best_state)", "pass", "LSTM keeps the last epoch, not the best"),
    # ---- sprint 03 reviews ----
    (
        "sql/raw/load_forecast_log.sql",
        "    where log_forecast.kind = 'hindcast';",
        ";",
        "same-day rerun rewrites a live forecast",
    ),
    (
        "sql/raw/load_actual_daily.sql",
        "is distinct from (excluded.tmax_c, excluded.tmin_c, excluded.precip_mm)",
        "is not null",
        "identical reload rewrites every row",
    ),
    (
        "sql/checks/checksum.sql",
        "cast(row(city, model, ts_local, lead_days, temp_c) as text)",
        "cast(row(city, model, ts_local, lead_days) as text)",
        "checksum blind to forecast values",
    ),
    (WH, "    assert_test_database(con.execute", "    str(con.execute", "reset skips its guard"),
    (
        WH,
        '        for path in sorted(Path(directory or SQL_DIR / "migrations").glob("*.sql")):',
        '        for path in sorted(Path(directory or SQL_DIR / "migrations").glob("*.sql"), reverse=True):',
        "migrations run newest first",
    ),
    (M, ".mean().shift(int(lead) + 1)", ".mean().shift(int(lead) + 2)", "recent bias a day late"),
    (M, ".ffill().shift(lead + 1)", ".ffill().shift(lead + 2)", "adaptive range a day late"),
    (
        M,
        "roll = known.dropna().rolling(window, min_periods=min_n)",
        "roll = known.dropna().rolling(window * 2, min_periods=min_n)",
        "adaptive range window doubled",
    ),
    (
        P,
        'replay = long["bt"].assign(lead_days=long["bt"]["lead_days"] - 1)',
        'replay = long["bt"].assign(lead_days=long["bt"]["lead_days"])',
        "long replay filed a day early",
    ),
    (
        P,
        'pred_c=(out["decay"]["pred_c"] + out["lstm"]["pred_c"]) / 2',
        'pred_c=out["lstm"]["pred_c"]',
        "mix is not the average",
    ),
    (
        S,
        "                clean[k] = v.isoformat()  # dates arrive",
        "                clean[k] = v.date().isoformat()  # dates arrive",
        "timestamps lose their time",
    ),
    (
        S,
        '        return state["pool"].connection()',
        '        return state["pool"].getconn()',
        "request keeps its pooled connection",
    ),
    (OB, 'if note and "\\x00" in note:', "if False:", "unstorable note reaches the driver"),
    # ---- sprint 04: the assistant ----
    (
        AT,
        'con.execute("set local role weatherwise_reader")',
        'con.execute("select 1")',
        "tools run with full privileges",
    ),
    (
        AT,
        "[ms])\n            return con.execute(sql, params)",
        "['0'])\n            return con.execute(sql, params)",
        "tool queries have no timeout",
    ),
    (AT, 'if done and done[0]["status"] == "ok":', "if False:", "a finished tool call runs again"),
    (
        AT,
        """call_id = f"{thread_id}:{call['id']}\"""",
        "call_id = call['id']",
        "threads share tool call ids",
    ),
    (
        AT,
        'out[k[:-2] + "_f"] = round(v * 1.8, 1)',
        'out[k[:-2] + "_f"] = round(v * 1.8 + 32, 1)',
        "a miss converted as a temperature",
    ),
    (
        AT,
        "RETRIES = 2  # after the first attempt",
        "RETRIES = 0  # after the first attempt",
        "tool failures are not retried",
    ),
    (AT, "sleep(0.5 * 2**attempt)", "sleep(0.5)", "retries do not back off"),
    (
        AT,
        'model_config = ConfigDict(extra="forbid")',
        'model_config = ConfigDict(extra="ignore")',
        "unknown tool arguments accepted",
    ),
    (
        AT,
        "days: int = Field(7, ge=1, le=30,",
        "days: int = Field(7, ge=1, le=3000,",
        "outlook days unbounded",
    ),
    (
        AT,
        "preferences(ctx.store, ctx.user_id).items()",
        'preferences(ctx.store, "local").items()',
        "preferences leak between users",
    ),
    (
        AT,
        '            status, failure = "error", exc\n            attempt = RETRIES\n',
        '            status, failure = "error", exc\n',
        "a permission error is retried",
    ),
    (AT, 'if v.upper() not in ("C", "F"):', "if False:", "any unit accepted as a preference"),
    (AG, "slack = 0.5 * 10**-decimals + 1e-9", "slack = 5.0", "number check accepts near misses"),
    (
        AG,
        "            values.update(float(p) for p in m.groups())\n",
        "",
        "day of month not supported by a date",
    ),
    (
        AG,
        'text = LIST_MARK.sub(" ", ISO_DATE.sub(" ", text))',
        'text = ISO_DATE.sub(" ", text)',
        "list numbering flagged as invented",
    ),
    (
        AG,
        'bad = [d for d in ISO_DATE.findall(text) if "-".join(d) not in dates]',
        "bad = []",
        "invented dates pass the number check",
    ),
    (
        GR,
        'if state.get("rewrites", 0) < 1:',
        'if state.get("rewrites", 0) < 0:',
        "no rewrite offered",
    ),
    (
        GR,
        '"messages": [AIMessage(content=REFUSAL, id=draft.id)],',
        '"messages": [],',
        "an unsupported number is shown",
    ),
    (GR, "        if used >= limit:\n", "        if False:\n", "model call cap removed"),
    (
        GR,
        '"prefs": toolbox.preferences(store, user),',
        '"prefs": {},',
        "saved preferences never reach the model",
    ),
    (
        GR,
        "or (isinstance(m, HumanMessage) and not internal(m)):",
        "or isinstance(m, HumanMessage):",
        "the correction note counts as a source",
    ),
    (
        GR,
        '    if not os.environ.get("ANTHROPIC_API_KEY"):\n',
        "    if False:\n",
        "missing key not reported",
    ),
    (
        GR,
        "            if isinstance(m, HumanMessage) and not internal(m):\n                out.append",
        "            if isinstance(m, HumanMessage):\n                out.append",
        "internal notes shown in the history",
    ),
    (
        "sql/agent/get_outlook.sql",
        "select max(newest.issued_on) from log_forecast as newest",
        "select min(newest.issued_on) from log_forecast as newest",
        "assistant reads an old outlook",
    ),
    (
        "sql/agent/get_outlook.sql",
        "and lead_days <= %(days)s",
        "and lead_days <= 30",
        "outlook ignores the days asked for",
    ),
    (
        "sql/agent/check_day.sql",
        "where city = %(city)s and date = %(day)s",
        "where city = %(city)s",
        "check_day ignores the day",
    ),
    (
        "sql/agent/get_forecast_error_by_lead.sql",
        "round(cast(100 * leads.share_off_3c as numeric), 1)",
        "round(cast(leads.share_off_3c as numeric), 1)",
        "share reported as a fraction, labelled percent",
    ),
    (
        "sql/migrations/002_agent.sql",
        "grant select on log_forecast, app_model_eval, app_run to weatherwise_reader;",
        "grant select on log_forecast, app_model_eval, app_run, raw_actual_daily to weatherwise_reader;",
        "reader role can read raw tables",
    ),
    (
        "sql/agent/grant_reader.sql",
        "execute format('grant select on %I to weatherwise_reader', mart);",
        "perform 1;",
        "marts unreadable after a rebuild",
    ),
]


# Sprint-04 review: grounding.py was rewritten, so its first mutants are replaced, and the
# fixes made after the two reviews get their own.
STALE = {
    "number check accepts near misses",
    "day of month not supported by a date",
    "list numbering flagged as invented",
    "invented dates pass the number check",
}
CFG = "src/weatherwise/config.py"
MUTATIONS = [m for m in MUTATIONS if m[3] not in STALE] + [
    (
        AG,
        "slack = 0.5 * 10**-decimals + 1e-9 if decimals else 1e-9",
        "slack = 5.0",
        "number check accepts near misses",
    ),
    (
        AG,
        "slack = 0.5 * 10**-decimals + 1e-9 if decimals else 1e-9",
        "slack = 0.5 * 10**-decimals + 1e-9",
        "a whole number matches any value that rounds to it",
    ),
    (
        AG,
        "            values.add(float(y))\n",
        "            values.update((float(y), float(m), float(d)))\n",
        "day of month counts as any number",
    ),
    (
        AG,
        "        if not 1 <= day <= 31:\n",
        "        if False:\n",
        "a number after may is read as a date",
    ),
    (
        AG,
        'text = LIST_MARK.sub(" ", MONTH_DAY.sub(written_date, text))',
        "text = MONTH_DAY.sub(written_date, text)",
        "list numbering flagged as invented",
    ),
    (
        AG,
        'bad = ["-".join(d) for d in ISO_DATE.findall(text) if tuple(map(int, d)) not in dates]',
        "bad = []",
        "invented dates pass the number check",
    ),
    (
        AG,
        "            bad.append(m.group(0))\n        return",
        "            pass\n        return",
        "an invented written date passes",
    ),
    (
        AT,
        'con.execute("set local transaction_read_only = on")',
        'con.execute("select 1")',
        "tool transaction is not read-only",
    ),
    (
        AT,
        'if (done[0]["tool"], done[0]["args"]) != (name, raw):',
        "if False:",
        "a reused call id is answered from the log",
    ),
    (
        AT,
        "        if v is not None and k in tool.temps:",
        "        if k in tool.temps:",
        "a missing value crashes the conversion",
    ),
    (
        AT,
        'self.value = f"{n:g} {unit} ({other})"',
        'self.value = f"{round(c, 1)} C ({round(c * 1.8 + 32, 1)} F)"',
        "the user's threshold number is rewritten",
    ),
    (
        AT,
        "ctx.store.put((PREFS, ctx.user_id), args.key",
        'ctx.store.put((PREFS, "local"), args.key',
        "preferences saved under the wrong user",
    ),
    (AT, '"rows": rows[:MAX_ROWS]}', '"rows": rows}', "a huge result is sent whole"),
    (
        AT,
        "        except Exception as exc:  # a permission, SQL or code error will not fix itself",
        "        except psycopg.Error as exc:  # a permission, SQL or code error will not fix itself",
        "a bug in a tool strands the conversation",
    ),
    (
        GR,
        "            if self.graph.get_state(config).next:\n",
        "            if False:\n",
        "a new question lands on an unfinished run",
    ),
    (
        GR,
        '            if not self.graph.get_state(config).values.get("messages"):\n',
        "            if False:\n",
        "resuming an unknown thread crashes",
    ),
    (
        GR,
        'if reason in STOPPED and (reason != "max_tokens" or not reply.tool_calls):',
        "if False:",
        "a refusal or cut-off reply is shown as the answer",
    ),
    (
        GR,
        'rejected = getattr(exc, "status_code", None) in (400, 401, 403, 404)',
        "rejected = False",
        "a bad key looks like an outage",
    ),
    (
        GR,
        '            "error": None,\n            "unsupported": [],\n',
        '            "unsupported": [],\n',
        "an old error sticks to the conversation",
    ),
    (
        GR,
        "        asked = max(",
        "        asked = min(",
        "earlier questions' tool calls reported again",
    ),
    (
        GR,
        'sources.extend(json.dumps(c["args"]) for c in m.tool_calls)',
        "pass",
        "tool arguments are not a source",
    ),
    (GR, ', json.dumps(state.get("prefs"))]', "]", "saved preferences are not a source"),
    (
        "sql/agent/get_outlook.sql",
        "    and kind = 'live'\n    and lead_days",
        "    and lead_days",
        "a replayed forecast leaks into the outlook",
    ),
    (
        "sql/agent/grant_reader.sql",
        "        if to_regclass(mart) is not null then",
        "        if true then",
        "assistant cannot start before the first run",
    ),
    (CFG, 'encoding="utf-8-sig"', 'encoding="utf-8"', "a BOM hides the first key"),
    (
        CFG,
        "        if value and not os.environ.get(key):",
        "        if value:",
        ".env replaces a variable that is already set",
    ),
    (CFG, '.removeprefix("export ")', "", "export lines in .env are ignored"),
]


# ---- sprint 05: operations. Descriptions start with "s5:" so `mutation_check.py s5:` runs them.
OP = "src/weatherwise/ops.py"
EV = "src/weatherwise/agent/evals.py"
DRIFT = "sql/ops/drift.sql"
S5 = [
    (
        OP,
        'if row and row["status"] in ("ok", "waiting_approval"):',
        "if False:",
        "a finished day is run again",
    ),
    (
        OP,
        'if not state["drifted"] or state["mode"] == "reselect":',
        "if True:",
        "drift never pauses the run",
    ),
    (
        OP,
        'mode = "reselect" if decision == "approved" else "forecast"',
        'mode = "reselect"',
        "declining still retrains",
    ),
    (
        OP,
        "MAX_LAG = models.MAX_OBS_AGE_DAYS - 1",
        "MAX_LAG = 99",
        "stale data is not stopped at the check",
    ),
    (
        OP,
        '[f"actuals are {lag} day behind"] if lag > 0 else []',
        "[]",
        "late data is not mentioned",
    ),
    (
        "sql/ops/run_update.sql",
        "where run_id = %(run_id)s and status <> 'ok';",
        "where run_id = %(run_id)s;",
        "a finished run is flipped to failed",
    ),
    (
        OP,
        '                if state["mode"] == "reselect":\n',
        "                if True:\n",
        "every daily run re-chooses the methods",
    ),
    (
        OP,
        "if lead <= pipeline.SHORT_LEADS:",
        "if lead <= 0:",
        "stored short-range methods are ignored",
    ),
    (
        OP,
        "first_run = pinned(con, city) is None",
        "first_run = False",
        "a first run has no methods and does not choose any",
    ),
    (
        OP,
        'if row["status"] != "waiting_approval":',
        "if False:",
        "a decision is accepted for a run that is not waiting",
    ),
    (
        OP,
        '"drifted": [r for r in rows if r["drifted"]],',
        '"drifted": rows,',
        "every lead is reported as drifted",
    ),
    (OP, "raise Busy(", "print(", "two daily runs at once"),
    (
        OP,
        "if newest is not None and newest >= today:",
        "if False:",
        "a run for a past day is accepted",
    ),
    (
        OP,
        "            if decided:  # the answer given before this run failed still stands\n",
        "            if False:\n",
        "an approval is lost when the run fails",
    ),
    (
        OP,
        "                if last:  # asked and answered",
        "                if False:  # asked and answered",
        "the gate asks again the day after a decision",
    ),
    (
        OP,
        "if recent < pipeline.WINDOW:",
        "if False:",
        "a hole in the newest actuals is found too late",
    ),
    (
        OP,
        "if lead in used.index and used[lead] != method:",
        "if False:",
        "a swapped method is not reported",
    ),
    (
        OP,
        "return out if complete else None",
        "return out or None",
        "a half-finished selection is forecast from",
    ),
    (M, "if pin and pin.get(lead) in maes:", "if False:", "a pinned method is not used"),
    (
        P,
        'corr = models.LeadCorrector().fit(pairs, pin=pin.get("short"))',
        "corr = models.LeadCorrector().fit(pairs)",
        "the outlook ignores the pinned methods",
    ),
    (
        P,
        "chosen = pin if pin in val else choose_long(val_mae)",
        "chosen = choose_long(val_mae)",
        "the long-range pin is ignored",
    ),
    (
        DRIFT,
        "order by case when logged.kind = 'live' then 0 else 1 end, logged.issued_on",
        "order by case when logged.kind = 'live' then 1 else 0 end, logged.issued_on",
        "drift prefers the replay to what was issued",
    ),
    (DRIFT, "where age <= %(days)s", "where age <= 9999", "drift window unbounded"),
    (DRIFT, "recent.n_days >= %(min_days)s", "recent.n_days >= 0", "drift flagged on too few days"),
    (
        DRIFT,
        "and recent.recent_mae_c > %(ratio)s * chosen.test_mae_c",
        "and recent.recent_mae_c >= %(ratio)s * chosen.test_mae_c",
        "drift ratio boundary moved",
    ),
    (
        DRIFT,
        "and recent.recent_mae_c - chosen.test_mae_c > %(gap)s",
        "and recent.recent_mae_c - chosen.test_mae_c >= %(gap)s",
        "drift gap boundary moved",
    ),
    (DRIFT, "and logged.lead_days <= %(max_lead)s", "", "drift measured on uncorrected leads"),
    (
        "sql/ops/data_lag.sql",
        "(cast(%(today)s as date) - 1) - newest.last_day",
        "cast(%(today)s as date) - newest.last_day",
        "data lag off by one day",
    ),
    (
        "sql/ops/run_start.sql",
        "attempts = app_run_log.attempts + 1",
        "attempts = app_run_log.attempts",
        "attempts are not counted",
    ),
    (
        "sql/ops/run_start.sql",
        "else cast('{}' as jsonb)",
        "else app_run_log.detail",
        "a rerun keeps the failed attempt's record",
    ),
    (
        "sql/ops/run_start.sql",
        "then jsonb_build_object('decision', app_run_log.detail -> 'decision')",
        "then cast('{}' as jsonb)",
        "a rerun forgets the decision",
    ),
    (
        "sql/ops/run_supersede.sql",
        "and today < %(today)s",
        "and today < date '1900-01-01'",
        "an unanswered run stays open",
    ),
    (
        "sql/ops/last_decision.sql",
        "and today >= cast(%(today)s as date) - %(days)s",
        "",
        "one decision silences the gate forever",
    ),
    (
        "sql/ops/stamp_run.sql",
        "    today = %(today)s,",
        "    today = today,",
        "the run stamp does not move",
    ),
    (
        EV,
        "v = _round(_round(v, places) * 1.8, 1)",
        "v = _round(_round(v, places) * 1.8 + 32, 1)",
        "eval key converts a gap as a temperature",
    ),
    (
        EV,
        "v = _round(_round(v, places) * 1.8 + 32, 1)",
        "v = _round(float(v) * 1.8 + 32, 1)",
        "eval key converts before rounding",
    ),
    (EV, "rounding=ROUND_HALF_UP", "rounding=ROUND_HALF_EVEN", "eval key rounds half to even"),
    (
        EV,
        '            return {"passed": False, "why": "the answer was refused by the number check"}',
        "            pass",
        "a refused answer can pass the eval",
    ),
    (
        EV,
        "        if float(value) not in _stated(answer):\n",
        "        if False:\n",
        "eval passes without the expected numbers",
    ),
    (
        EV,
        "        if label and not any(\n",
        "        if False and not any(\n",
        "eval passes numbers stated the wrong way round",
    ),
    (
        EV,
        "            if value.lower() not in answer.lower():\n",
        "            if False:\n",
        "eval passes without the expected day",
    ),
    (
        EV,
        'if case.get("declines") and not DECLINES.search(answer):',
        "if False:",
        "eval passes a guess where a decline is required",
    ),
    (
        EV,
        "stated = [n for n in figures(answer) if n not in asked]",
        "stated = []",
        "eval ignores figures in a no-figure answer",
    ),
    (EV, 'if case["tool"] not in used:', "if False:", "eval does not check which tool was used"),
    (
        EV,
        r'(?!\d|\.\d)", answer):',
        r'(?![\d.]\d)", answer):',
        "eval bans a different number that starts the same",
    ),
    (GR, "    if len(asked) <= keep:\n", "    if True:\n", "long conversations are sent whole"),
    (
        GR,
        'messages, dropped = recent(state["messages"], KEEP_QUESTIONS)\n        draft',
        'messages, dropped = state["messages"], 0\n        draft',
        "the number check sees turns the model no longer does",
    ),
    (
        GR,
        'turned_down = [*state.get("rejected", []), {"draft": text_of(draft), "unsupported": bad}]',
        "turned_down = []",
        "rejected drafts are not kept for audit",
    ),
    (S, 'out.pop("rejected")', 'out.get("rejected")', "refused drafts are sent to the browser"),
]
MUTATIONS += [(f, old, new, f"s5: {what}") for f, old, new, what in S5]

MODEL_TESTS = ["test_sprint2_models.py", "test_models.py", "test_sprint3_review.py"]


def test_order(rel: str) -> list[str]:
    """Every test file, the ones most likely to notice a change in `rel` first. The whole suite
    still runs before a mutant counts as SURVIVED; with -x a kill just comes sooner."""
    names = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    model_code = rel in (M, P, D)
    first = [n for n in names if (n in MODEL_TESTS) == model_code]
    if "agent" in rel or rel.endswith("config.py"):
        first = ["test_sprint4_agent.py"]
    if "ops" in rel or rel.endswith(("evals.py", "models.py", "pipeline.py", "graph.py")):
        first = ["test_sprint5_ops.py", *first]
    return [f"tests/{n}" for n in first + [n for n in names if n not in first]]


LIMIT_S = 1500  # one mutant: the whole suite takes about 750 s on a slow day


def drop_test_schema() -> None:
    """Empty the test database completely; the next test connection migrates it again."""
    url = os.environ.get(
        "WEATHERWISE_TEST_DATABASE_URL",
        "postgresql://weatherwise:weatherwise@127.0.0.1:15480/weatherwise_test",
    )
    with psycopg.connect(url, autocommit=True) as con:
        name = con.execute("select current_database()").fetchall()[0][0]
        if not name.endswith("_test"):
            raise RuntimeError(f"refusing to drop the schema of {name!r}")
        con.execute("drop schema if exists agent cascade")
        con.execute("drop schema public cascade")
        con.execute("create schema public")


def main() -> int:
    print(f"# mutation run {datetime.now(UTC):%FT%TZ}; KILLED = a test failed (exit 1)")
    # optional arguments: run only the mutants whose file path or description contains a word
    # MUTATION_SLICE=i/n takes every n-th of them from the i-th (parallel workers, each with
    # its own copy of the tree and its own test database); MUTATION_SKIP names an earlier
    # output file whose KILLED mutants are not run again
    todo = [
        m
        for m in MUTATIONS
        if not sys.argv[1:] or any(w in m[0] or w in m[3] for w in sys.argv[1:])
    ]
    if os.environ.get("MUTATION_SKIP"):
        done = Path(os.environ["MUTATION_SKIP"]).read_text(encoding="utf-8")
        todo = [m for m in todo if f"KILLED   {m[3]}" not in done]
    if os.environ.get("MUTATION_SLICE"):
        i, n = (int(x) for x in os.environ["MUTATION_SLICE"].split("/"))
        todo = todo[i::n]
    bad = 0
    for rel, old, new, what in todo:
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        if old not in src:
            print(f"MISSING  {what}: pattern not found in {rel}")
            bad += 1
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        migration = rel.startswith("sql/migrations/")
        try:
            if migration:
                drop_test_schema()
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-rf", "--tb=no", *test_order(rel)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=LIMIT_S,
            )
        except subprocess.TimeoutExpired:
            r = subprocess.CompletedProcess([], 2, f"no result in {LIMIT_S} s", "")
        finally:
            path.write_text(src, encoding="utf-8")
            if migration:
                drop_test_schema()
        killer = next(
            (ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED")), "-"
        )
        status = {0: "SURVIVED", 1: "KILLED  "}.get(r.returncode, "CRASHED ")
        bad += r.returncode != 1
        print(f"{status} {what:36s} by {killer}")
    print(f"\n{len(todo) - bad}/{len(todo)} mutations killed by a failing test")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
