-- The check the site runs: what the user saw on a day against what was forecast for that day.
-- grain: one row per city, date, variable, lead. A live forecast wins over a hindcast.
-- error = forecast - observed (positive = forecast too warm). A view, so new entries show at once.
drop view if exists mart_verification cascade;

create view mart_verification as
with ranked as (
    select
        log_forecast.*,
        row_number() over (
            partition by
                log_forecast.city, log_forecast.date, log_forecast.variable, log_forecast.lead_days
            order by case when log_forecast.kind = 'live' then 0 else 1 end, log_forecast.issued_on
        ) as pick
    from log_forecast
),

observed as (
    select
        city,
        date,
        'tmax' as variable,
        tmax_c as observed_c
    from raw_user_observation
    where tmax_c is not null
    union all
    select
        city,
        date,
        'tmin' as variable,
        tmin_c as observed_c
    from raw_user_observation
    where tmin_c is not null
),

era5 as (
    select
        city,
        date,
        'tmax' as variable,
        tmax_c as era5_c
    from stg_actual_daily
    union all
    select
        city,
        date,
        'tmin' as variable,
        tmin_c as era5_c
    from stg_actual_daily
)

select
    ranked.city,
    ranked.date,
    ranked.variable,
    ranked.lead_days,
    ranked.kind,
    ranked.issued_on,
    ranked.method,
    ranked.pred_c,
    ranked.lo_c,
    ranked.hi_c,
    ranked.published_c,
    observed.observed_c,
    era5.era5_c,
    ranked.pred_c - observed.observed_c as our_error_c,
    ranked.published_c - observed.observed_c as published_error_c,
    (observed.observed_c between ranked.lo_c and ranked.hi_c) as inside_range
from ranked
inner join observed
    on
        ranked.city = observed.city
        and ranked.date = observed.date
        and ranked.variable = observed.variable
left join era5
    on
        ranked.city = era5.city
        and ranked.date = era5.date
        and ranked.variable = era5.variable
where ranked.pick = 1;
