-- parameters: city
select
    variable,
    lead_days,
    method,
    cv_mae_c,
    test_mae_c,
    test_days,
    chosen,
    coverage_pct
from app_model_eval
where city = %(city)s
order by variable, lead_days, method;
