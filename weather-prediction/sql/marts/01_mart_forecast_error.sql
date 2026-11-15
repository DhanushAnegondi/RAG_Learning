-- One row per city, date, lead, variable. error_c = forecast - actual (positive = too warm).
create or replace table mart_forecast_error as
with published as (
    select * from stg_published_daily
),

actual as (
    select * from stg_actual_daily
),

-- grain: actual is unique on (city, date) by primary key; published on (city, date, lead_days)
paired as (
    select
        published.city,
        published.date,
        published.lead_days,
        published.tmax_c as fc_tmax,
        published.tmin_c as fc_tmin,
        actual.tmax_c as obs_tmax,
        actual.tmin_c as obs_tmin
    from published
    inner join actual
        on published.city = actual.city and published.date = actual.date
),

long_form as (
    select
        city,
        date,
        lead_days,
        'tmax' as variable,
        fc_tmax as forecast_c,
        obs_tmax as actual_c
    from paired
    union all
    select
        city,
        date,
        lead_days,
        'tmin' as variable,
        fc_tmin as forecast_c,
        obs_tmin as actual_c
    from paired
)

select
    long_form.city,
    long_form.date,
    long_form.lead_days,
    long_form.variable,
    long_form.forecast_c,
    long_form.actual_c,
    long_form.forecast_c - long_form.actual_c as error_c
from long_form;
