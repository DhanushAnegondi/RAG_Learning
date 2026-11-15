-- Hourly published forecasts -> daily max/min per local date and lead.
-- A day counts only with all 24 hours, so a partial day never fakes a max.
create or replace view stg_published_daily as
with source as (
    select * from raw_published_hourly
),

by_day as (
    select
        source.city,
        source.lead_days,
        cast(source.ts_local as date) as date,
        max(source.temp_c) as tmax_c,
        min(source.temp_c) as tmin_c,
        count(*) as n_hours
    from source
    group by source.city, source.lead_days, cast(source.ts_local as date)
)

select
    by_day.city,
    by_day.date,
    by_day.lead_days,
    by_day.tmax_c,
    by_day.tmin_c
from by_day
where by_day.n_hours = 24;
