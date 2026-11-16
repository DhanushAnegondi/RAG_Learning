-- tool get_outlook. parameters: city, days. The newest forecast issued live, first `days` days,
-- one row per day with high and low side by side.
select
    date,
    lead_days,
    issued_on,
    cast(
        round(cast(max(pred_c) filter (where variable = 'tmax') as numeric), 1)
        as double precision
    ) as high_c,
    cast(
        round(cast(max(lo_c) filter (where variable = 'tmax') as numeric), 1)
        as double precision
    ) as high_low_end_c,
    cast(
        round(cast(max(hi_c) filter (where variable = 'tmax') as numeric), 1)
        as double precision
    ) as high_high_end_c,
    cast(
        round(cast(max(published_c) filter (where variable = 'tmax') as numeric), 1)
        as double precision
    ) as published_high_c,
    cast(
        round(cast(max(pred_c) filter (where variable = 'tmin') as numeric), 1)
        as double precision
    ) as low_c,
    cast(
        round(cast(max(lo_c) filter (where variable = 'tmin') as numeric), 1)
        as double precision
    ) as low_low_end_c,
    cast(
        round(cast(max(hi_c) filter (where variable = 'tmin') as numeric), 1)
        as double precision
    ) as low_high_end_c,
    cast(
        round(cast(max(published_c) filter (where variable = 'tmin') as numeric), 1)
        as double precision
    ) as published_low_c,
    to_char(date, 'FMDay') as weekday
from log_forecast
where
    city = %(city)s
    and kind = 'live'
    and lead_days <= %(days)s
    and issued_on = (
        select max(newest.issued_on) from log_forecast as newest
        where newest.city = %(city)s and newest.kind = 'live'
    )
group by date, lead_days, issued_on
order by date;
