-- parameters: city. Day-before forecasts replayed on the held-out year, next to what happened.
select
    replay.date,
    replay.variable,
    cast(round(cast(replay.pred_c as numeric), 2) as double precision) as pred_c,
    cast(round(cast(replay.lo_c as numeric), 2) as double precision) as lo_c,
    cast(round(cast(replay.hi_c as numeric), 2) as double precision) as hi_c,
    cast(round(cast(replay.published_c as numeric), 2) as double precision) as published_c,
    case when replay.variable = 'tmax' then actual.tmax_c else actual.tmin_c end as actual_c
from log_forecast as replay
inner join stg_actual_daily as actual
    on replay.city = actual.city and replay.date = actual.date
where replay.city = %(city)s and replay.kind = 'hindcast' and replay.lead_days = 1
order by replay.date desc, replay.variable asc
limit 240;
