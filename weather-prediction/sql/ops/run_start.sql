-- parameters: run_id, city, today. Starts a run, or begins another attempt at it. A new
-- attempt starts with a clean slate, except a decision already given at the gate, which
-- stands. A run that is ok is never touched (no row comes back).
insert into app_run_log (run_id, city, today, status, step)
values (%(run_id)s, %(city)s, %(today)s, 'running', 'start')
on conflict (run_id) do update
    set
        status = 'running',
        step = 'start',
        mode = null,
        error = null,
        finished_at = null,
        attempts = app_run_log.attempts + 1,
        updated_at = localtimestamp,
        detail = case
            when jsonb_exists(app_run_log.detail, 'decision')
                then jsonb_build_object('decision', app_run_log.detail -> 'decision')
            else cast('{}' as jsonb)
        end
    where app_run_log.status <> 'ok'
returning attempts;
