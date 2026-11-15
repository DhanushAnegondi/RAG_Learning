-- tool get_forecast_error_by_lead. parameters: city, variable. How wrong the published
-- forecast has been, by days ahead, next to the test-window error of the method this project
-- chose for that lead (leads 1-7 only have a published forecast).
select
    leads.lead_days,
    leads.n_days,
    cast(round(cast(leads.bias_c as numeric), 2) as double precision) as published_bias_c,
    cast(round(cast(leads.mae_c as numeric), 2) as double precision) as published_avg_miss_c,
    cast(round(cast(100 * leads.share_off_3c as numeric), 1) as double precision)
        as published_pct_days_off_3c_or_more,
    cast(round(cast(leads.max_abs_error_c as numeric), 1) as double precision)
        as published_worst_miss_c,
    chosen.method as weatherwise_method,
    cast(round(cast(chosen.test_mae_c as numeric), 2) as double precision)
        as weatherwise_avg_miss_last_12_months_c,
    cast(round(cast(chosen.coverage_pct as numeric), 1) as double precision)
        as weatherwise_pct_days_inside_range
from mart_error_by_lead as leads
left join app_model_eval as chosen
    on
        leads.city = chosen.city
        and leads.variable = chosen.variable
        and leads.lead_days = chosen.lead_days
        and chosen.chosen
where leads.city = %(city)s and leads.variable = %(variable)s
order by leads.lead_days;
