-- parameters: city, city. The outlook is the newest forecast issued live, nothing older.
select
    date,
    lead_days,
    variable,
    issued_on,
    method,
    cast(round(cast(pred_c as numeric), 2) as double precision) as pred_c,
    cast(round(cast(lo_c as numeric), 2) as double precision) as lo_c,
    cast(round(cast(hi_c as numeric), 2) as double precision) as hi_c,
    cast(round(cast(published_c as numeric), 2) as double precision) as published_c
from log_forecast
where
    city = %(city)s
    and kind = 'live'
    and issued_on = (
        select max(newest.issued_on) from log_forecast as newest
        where newest.city = %(city)s and newest.kind = 'live'
    )
order by date, variable;
