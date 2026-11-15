-- Stored tables. Primary keys make reloads idempotent (insert ... on conflict do update).
-- Naming: raw_ landed as fetched, log_ append-style history, app_ written by the pipeline.
-- Staging (stg_) and marts (mart_) are rebuilt from these by sql/staging and sql/marts.
create table raw_actual_daily (
    city text not null,
    date date not null,
    tmax_c double precision,
    tmin_c double precision,
    precip_mm double precision,
    loaded_at timestamp not null default localtimestamp,
    primary key (city, date)
);

-- Hourly temperature as forecast lead_days before ts_local (Open-Meteo previous_dayN),
-- one series per weather model. best_match is the forecast Open-Meteo publishes by default.
create table raw_published_hourly (
    city text not null,
    model text not null,
    ts_local timestamp not null,
    lead_days integer not null,
    temp_c double precision not null,
    loaded_at timestamp not null default localtimestamp,
    primary key (city, model, ts_local, lead_days)
);

-- Live forecast as issued on issued_on, one series per weather model.
create table raw_live_forecast (
    city text not null,
    model text not null,
    issued_on date not null,
    date date not null,
    tmax_c double precision,
    tmin_c double precision,
    precip_mm double precision,
    loaded_at timestamp not null default localtimestamp,
    primary key (city, model, issued_on, date)
);

-- What the user saw on a day (typed into the site). One row per city and date; re-entry edits.
create table raw_user_observation (
    city text not null,
    date date not null,
    tmax_c double precision,
    tmin_c double precision,
    note text,
    entered_at timestamp not null,
    primary key (city, date)
);

-- Every forecast this project made. kind = live (the first one issued that day; the loader
-- never updates a live row) or
-- hindcast (replayed on the held-out test window by models that never saw it).
create table log_forecast (
    city text not null,
    kind text not null check (kind in ('live', 'hindcast')),
    issued_on date not null,
    date date not null,
    variable text not null check (variable in ('tmax', 'tmin')),
    lead_days integer not null check (lead_days >= 1),
    pred_c double precision not null,
    lo_c double precision not null,
    hi_c double precision not null,
    published_c double precision,
    method text not null,
    logged_at timestamp not null,
    primary key (city, kind, issued_on, date, variable)
);

-- Leaderboard: every candidate method per lead, scored in CV (inside training) and on the test
-- window. chosen marks the method the outlook uses.
create table app_model_eval (
    city text not null,
    variable text not null,
    lead_days integer not null,
    method text not null,
    cv_mae_c double precision,
    test_mae_c double precision,
    test_days integer,
    chosen boolean not null,
    coverage_pct double precision,
    primary key (city, variable, lead_days, method)
);

create table app_run (
    city text not null,
    run_utc timestamp not null,
    today date not null,
    test_start date not null,
    primary key (city)
);
