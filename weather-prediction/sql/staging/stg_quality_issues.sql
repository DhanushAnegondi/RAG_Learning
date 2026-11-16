-- Cleaning rules, one row per rejected raw row with the reason. Staging views exclude these.
-- Fence: surface air temperature on Earth has stayed inside -90..57 C; -60..60 is a safe limit
-- for the places this project forecasts.
drop view if exists stg_quality_issues cascade;

create view stg_quality_issues as
select
    actual.city,
    'raw_actual_daily' as source,
    cast(actual.date as timestamp) as seen_at,
    case
        when actual.tmax_c is null or actual.tmin_c is null then 'missing max or min'
        when
            actual.tmax_c not between -60 and 60 or actual.tmin_c not between -60 and 60
            then 'temperature outside -60..60 C'
        else 'max below min'
    end as reason
from raw_actual_daily as actual
where
    actual.tmax_c is null
    or actual.tmin_c is null
    or actual.tmax_c not between -60 and 60
    or actual.tmin_c not between -60 and 60
    or actual.tmax_c < actual.tmin_c
union all
select
    hourly.city,
    'raw_published_hourly' as source,
    hourly.ts_local as seen_at,
    'temperature outside -60..60 C' as reason
from raw_published_hourly as hourly
where hourly.temp_c not between -60 and 60;
