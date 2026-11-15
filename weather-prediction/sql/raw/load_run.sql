insert into app_run (city, run_utc, today, test_start)
select
    incoming.city,
    incoming.run_utc,
    incoming.today,
    incoming.test_start
from incoming
on conflict (city) do update
    set
        run_utc = excluded.run_utc,
        today = excluded.today,
        test_start = excluded.test_start;
