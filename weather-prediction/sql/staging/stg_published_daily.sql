-- Hourly published forecasts -> daily max/min per local date, lead and weather model.
-- A day counts only with all 24 hours, so a partial day never fakes a max.
drop view if exists stg_published_daily cascade;

create view stg_published_daily as
with source as (
    select * from raw_published_hourly
    where temp_c between -60 and 60
),

by_day as (
    select
        source.city,
        source.model,
        source.lead_days,
        cast(source.ts_local as date) as date,
        max(source.temp_c) as tmax_c,
        min(source.temp_c) as tmin_c,
        count(*) as n_hours
    from source
    group by source.city, source.model, source.lead_days, cast(source.ts_local as date)
)

select
    by_day.city,
    by_day.model,
    by_day.date,
    by_day.lead_days,
    by_day.tmax_c,
    by_day.tmin_c
from by_day
where by_day.n_hours = 24;
