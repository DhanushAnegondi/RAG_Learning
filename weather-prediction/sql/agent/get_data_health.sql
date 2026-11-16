-- tool get_data_health. parameters: city. What data arrived, what survived cleaning, and when
-- the forecast was last run.
select
    quality.source,
    quality.raw_rows,
    quality.usable_days,
    quality.first_date,
    quality.last_date,
    quality.rejected_days,
    quality.missing_days,
    runs.today as last_run_day,
    runs.test_start as test_window_start
from mart_data_quality as quality
left join app_run as runs on quality.city = runs.city
where quality.city = %(city)s
order by quality.source;
