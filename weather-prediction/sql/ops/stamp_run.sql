-- parameters: city, today, run_utc. A forecast-only run moves the run stamp forward; the
-- test window start stays that of the last selection.
update app_run
set
    today = %(today)s,
    run_utc = %(run_utc)s
where city = %(city)s;
