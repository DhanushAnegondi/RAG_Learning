-- Running score from the entries typed into the site: our forecast against the published
-- one, by lead. our_mae_same_days_c repeats our error on only the rows that have a published
-- value, so the two columns compare like with like.
drop view if exists mart_scoreboard cascade;

create view mart_scoreboard as
select
    checks.city,
    checks.variable,
    checks.lead_days,
    cast(round(cast(avg(abs(checks.our_error_c)) as numeric), 2) as double precision)
        as our_mae_c,
    cast(round(cast(avg(abs(checks.published_error_c)) as numeric), 2) as double precision)
        as published_mae_c,
    cast(
        round(
            cast(
                avg(case when checks.published_c is not null then abs(checks.our_error_c) end)
                as numeric
            ),
            2
        ) as double precision
    ) as our_mae_same_days_c,
    cast(
        round(avg(case when checks.inside_range then 1.0 else 0.0 end), 3) as double precision
    ) as share_inside_range,
    cast(round(cast(avg(checks.observed_c - checks.era5_c) as numeric), 2) as double precision)
        as your_reading_minus_era5_c,
    count(*) as n_checks
from mart_verification as checks
group by checks.city, checks.variable, checks.lead_days;
