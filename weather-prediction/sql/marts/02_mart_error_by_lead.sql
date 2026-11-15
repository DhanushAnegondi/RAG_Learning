-- How wrong were published forecasts, by lead time. Shares are fractions of days (0-1).
create or replace table mart_error_by_lead as
with errors as (
    select * from mart_forecast_error
)

select
    errors.city,
    errors.variable,
    errors.lead_days,
    count(*) as n_days,
    round(avg(errors.error_c), 3) as bias_c,
    round(avg(abs(errors.error_c)), 3) as mae_c,
    round(sqrt(avg(errors.error_c * errors.error_c)), 3) as rmse_c,
    round(quantile_cont(errors.error_c, 0.1), 3) as p10_error_c,
    round(quantile_cont(errors.error_c, 0.9), 3) as p90_error_c,
    round(avg(case when abs(errors.error_c) >= 2 then 1.0 else 0.0 end), 4) as share_off_2c,
    round(avg(case when abs(errors.error_c) >= 3 then 1.0 else 0.0 end), 4) as share_off_3c,
    round(max(abs(errors.error_c)), 3) as max_abs_error_c
from errors
group by errors.city, errors.variable, errors.lead_days;
