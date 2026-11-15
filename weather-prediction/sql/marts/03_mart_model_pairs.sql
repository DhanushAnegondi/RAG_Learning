-- Training rows for the correction models: the published forecast next to the other weather
-- models' forecasts for the same day and lead, and what happened.
-- grain: one row per city, date, lead, variable. best_match must exist; the others may be null.
drop table if exists mart_model_pairs cascade;

create table mart_model_pairs as
with wide as (
    select
        published.city,
        published.date,
        published.lead_days,
        max(case when published.model = 'best_match' then published.tmax_c end) as tmax_best,
        max(case when published.model = 'gfs_seamless' then published.tmax_c end) as tmax_gfs,
        max(case when published.model = 'ecmwf_ifs025' then published.tmax_c end) as tmax_ecmwf,
        max(case when published.model = 'gem_seamless' then published.tmax_c end) as tmax_gem,
        max(case when published.model = 'best_match' then published.tmin_c end) as tmin_best,
        max(case when published.model = 'gfs_seamless' then published.tmin_c end) as tmin_gfs,
        max(case when published.model = 'ecmwf_ifs025' then published.tmin_c end) as tmin_ecmwf,
        max(case when published.model = 'gem_seamless' then published.tmin_c end) as tmin_gem
    from stg_published_daily as published
    group by published.city, published.date, published.lead_days
),

paired as (
    select
        wide.*,
        actual.tmax_c as obs_tmax,
        actual.tmin_c as obs_tmin
    from wide
    inner join stg_actual_daily as actual
        on wide.city = actual.city and wide.date = actual.date
    where wide.tmax_best is not null
)

select
    city,
    date,
    lead_days,
    'tmax' as variable,
    tmax_best as forecast_c,
    tmax_gfs as fc_gfs,
    tmax_ecmwf as fc_ecmwf,
    tmax_gem as fc_gem,
    obs_tmax as actual_c
from paired
union all
select
    city,
    date,
    lead_days,
    'tmin' as variable,
    tmin_best as forecast_c,
    tmin_gfs as fc_gfs,
    tmin_ecmwf as fc_ecmwf,
    tmin_gem as fc_gem,
    obs_tmin as actual_c
from paired;
