-- Row count and a content digest per stored table, over data columns only (not loaded_at).
-- Loading the same data twice must leave every line unchanged. row(...)::text keeps a
-- null in its position, so (null, 5) and (5, null) hash differently.
select
    'raw_actual_daily' as table_name,
    count(*) as n,
    coalesce(sum(hashtextextended(cast(row(city, date, tmax_c, tmin_c, precip_mm) as text), 0)), 0)
        as digest
from raw_actual_daily
union all
select
    'raw_published_hourly' as table_name,
    count(*) as n,
    coalesce(
        sum(hashtextextended(cast(row(city, model, ts_local, lead_days, temp_c) as text), 0)), 0
    )
        as digest
from raw_published_hourly
union all
select
    'raw_live_forecast' as table_name,
    count(*) as n,
    coalesce(
        sum(
            hashtextextended(
                cast(row(city, model, issued_on, date, tmax_c, tmin_c, precip_mm) as text), 0
            )
        ),
        0
    ) as digest
from raw_live_forecast
order by table_name;
