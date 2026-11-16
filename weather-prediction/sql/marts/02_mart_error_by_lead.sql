-- How wrong were published forecasts, by lead time. Shares are fractions of days (0-1).
drop table if exists mart_error_by_lead cascade;

create table mart_error_by_lead as
with errors as (
    select * from mart_forecast_error
)

select
    errors.city,
    errors.variable,
    errors.lead_days,
    count(*) as n_days,
    cast(round(cast(avg(errors.error_c) as numeric), 3) as double precision) as bias_c,
    cast(round(cast(avg(abs(errors.error_c)) as numeric), 3) as double precision) as mae_c,
    cast(
        round(cast(sqrt(avg(errors.error_c * errors.error_c)) as numeric), 3) as double precision
    ) as rmse_c,
    cast(
        round(
            cast(percentile_cont(0.1) within group (order by errors.error_c) as numeric), 3
        ) as double precision
    ) as p10_error_c,
    cast(
        round(
            cast(percentile_cont(0.9) within group (order by errors.error_c) as numeric), 3
        ) as double precision
    ) as p90_error_c,
    cast(
        round(avg(case when abs(errors.error_c) >= 2 then 1.0 else 0.0 end), 4) as double precision
    ) as share_off_2c,
    cast(
        round(avg(case when abs(errors.error_c) >= 3 then 1.0 else 0.0 end), 4) as double precision
    ) as share_off_3c,
    cast(round(cast(max(abs(errors.error_c)) as numeric), 3) as double precision)
        as max_abs_error_c
from errors
group by errors.city, errors.variable, errors.lead_days;
