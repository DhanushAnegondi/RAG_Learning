-- Raw landing tables. Primary keys make reloads idempotent (insert or replace).
create table if not exists raw_actual_daily (
    city varchar not null,
    date date not null,
    tmax_c double,
    tmin_c double,
    precip_mm double,
    loaded_at timestamp not null,
    primary key (city, date)
);

-- Hourly temperature as forecast lead_days before ts_local (Open-Meteo previous_dayN).
create table if not exists raw_published_hourly (
    city varchar not null,
    ts_local timestamp not null,
    lead_days integer not null,
    temp_c double not null,
    loaded_at timestamp not null,
    primary key (city, ts_local, lead_days)
);

-- Live forecast as issued on issued_on.
create table if not exists raw_live_forecast (
    city varchar not null,
    issued_on date not null,
    date date not null,
    tmax_c double,
    tmin_c double,
    precip_mm double,
    loaded_at timestamp not null,
    primary key (city, issued_on, date)
);
