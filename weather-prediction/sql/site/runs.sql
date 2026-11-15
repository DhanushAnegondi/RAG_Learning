-- One row per city that has been run: when, and the newest live forecast.
select
    app_run.city,
    app_run.run_utc,
    app_run.today,
    app_run.test_start
from app_run;
