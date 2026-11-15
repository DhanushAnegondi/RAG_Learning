-- tool get_scoreboard. parameters: city. Score on the user's own readings, by days ahead.
select
    variable,
    lead_days,
    n_checks,
    our_mae_c as weatherwise_avg_miss_c,
    published_mae_c as published_avg_miss_c,
    our_mae_same_days_c as weatherwise_avg_miss_same_days_c,
    cast(round(cast(100 * share_inside_range as numeric), 1) as double precision)
        as pct_readings_inside_range,
    your_reading_minus_era5_c as reading_minus_grid_c
from mart_scoreboard
where city = %(city)s
order by variable, lead_days;
