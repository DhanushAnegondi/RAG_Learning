-- parameters: run_id, city, today. A run still waiting for a decision when a later day
-- starts is closed: answering it now would forecast for a past day with newer data.
update app_run_log
set
    status = 'failed',
    error = 'no decision was given; superseded by ' || %(run_id)s,
    updated_at = localtimestamp,
    finished_at = localtimestamp
where city = %(city)s and status = 'waiting_approval' and today < %(today)s;
