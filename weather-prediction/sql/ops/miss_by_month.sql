-- parameters: city, variable, lead_days. Evidence behind a drift flag: this project's and
-- the published forecast's average miss and bias per month, from the replayed forecasts.
-- error = forecast - actual, so a bias below 0 means too cold.
with scored as (
    select
        to_char(logged.date, 'YYYY-MM') as year_month,
        logged.pred_c
        - case logged.variable when 'tmax' then actual.tmax_c else actual.tmin_c end
            as our_error_c,
        logged.published_c
        - case logged.variable when 'tmax' then actual.tmax_c else actual.tmin_c end
            as published_error_c
    from log_forecast as logged
    inner join stg_actual_daily as actual
        on logged.city = actual.city and logged.date = actual.date
    where
        logged.city = %(city)s
        and logged.kind = 'hindcast'
        and logged.variable = %(variable)s
        and logged.lead_days = %(lead_days)s
)

select
    year_month,
    cast(round(cast(avg(abs(our_error_c)) as numeric), 2) as double precision)
        as weatherwise_miss_c,
    cast(round(cast(avg(our_error_c) as numeric), 2) as double precision) as weatherwise_bias_c,
    cast(round(cast(avg(abs(published_error_c)) as numeric), 2) as double precision)
        as published_miss_c,
    cast(round(cast(avg(published_error_c) as numeric), 2) as double precision)
        as published_bias_c,
    count(*) as days
from scored
group by year_month
order by year_month;
