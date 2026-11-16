-- parameters: city
select
    variable,
    lead_days,
    n_days,
    bias_c,
    mae_c,
    rmse_c,
    p10_error_c,
    p90_error_c,
    share_off_2c,
    share_off_3c,
    max_abs_error_c
from mart_error_by_lead
where city = %(city)s
order by variable, lead_days;
