-- parameters: run_id
select
    run_id,
    city,
    today,
    status,
    step,
    mode,
    detail,
    error,
    attempts,
    started_at,
    finished_at
from app_run_log
where run_id = %(run_id)s;
