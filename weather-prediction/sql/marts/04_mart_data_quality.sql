-- Data health per city and source: how much arrived, how much survived cleaning, what is missing.
drop table if exists mart_data_quality cascade;

create table mart_data_quality as
with actual_raw as (
    select
        city,
        count(*) as raw_rows
    from raw_actual_daily
    group by city
),

actual_ok as (
    select
        city,
        count(*) as usable_days,
        min(date) as first_date,
        max(date) as last_date
    from stg_actual_daily
    group by city
),

hourly_raw as (
    select
        city,
        model,
        count(*) as raw_rows,
        count(distinct cast(ts_local as date)) as raw_days
    from raw_published_hourly
    where lead_days = 1
    group by city, model
),

hourly_ok as (
    select
        city,
        model,
        count(*) as usable_days,
        min(date) as first_date,
        max(date) as last_date
    from stg_published_daily
    where lead_days = 1
    group by city, model
)

select
    actual_raw.city,
    'actuals (ERA5 daily)' as source,
    actual_raw.raw_rows,
    actual_ok.usable_days,
    actual_ok.first_date,
    actual_ok.last_date,
    actual_raw.raw_rows - actual_ok.usable_days as rejected_days,
    (actual_ok.last_date - actual_ok.first_date) + 1 - actual_ok.usable_days
        as missing_days
from actual_raw
inner join actual_ok on actual_raw.city = actual_ok.city
union all
select
    hourly_raw.city,
    'forecast 1 day ahead: ' || hourly_raw.model as source,
    hourly_raw.raw_rows,
    hourly_ok.usable_days,
    hourly_ok.first_date,
    hourly_ok.last_date,
    hourly_raw.raw_days - hourly_ok.usable_days as rejected_days,
    (hourly_ok.last_date - hourly_ok.first_date) + 1 - hourly_ok.usable_days
        as missing_days
from hourly_raw
inner join hourly_ok on hourly_raw.city = hourly_ok.city and hourly_raw.model = hourly_ok.model;
