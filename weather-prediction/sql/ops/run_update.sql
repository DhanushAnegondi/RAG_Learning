-- parameters: run_id, status, step, mode, detail (json, merged into what is there), error.
-- A run that is ok is never changed again.
update app_run_log
set
    status = %(status)s,
    step = %(step)s,
    mode = coalesce(%(mode)s, mode),
    detail = detail || cast(%(detail)s as jsonb),
    error = %(error)s,
    updated_at = localtimestamp,
    finished_at = case when %(status)s in ('ok', 'failed') then localtimestamp end
where run_id = %(run_id)s and status <> 'ok';
