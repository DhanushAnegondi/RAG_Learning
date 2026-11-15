-- parameters: city
select
    variable,
    lead_days,
    n_checks,
    our_mae_c,
    published_mae_c,
    our_mae_same_days_c,
    share_inside_range,
    your_reading_minus_era5_c
from mart_scoreboard
where city = %(city)s
order by variable, lead_days;
