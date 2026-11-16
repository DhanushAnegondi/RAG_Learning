-- Sprint 05: one row per daily run, updated as the run moves through its steps.
-- status: running (also what a run cut off mid-step leaves behind), waiting_approval (drift
-- found, a person must decide), ok, failed. detail holds the drift table, the data lag,
-- warnings and the decision.
create table app_run_log (
    run_id text primary key,
    city text not null,
    today date not null,
    status text not null check (status in ('running', 'waiting_approval', 'ok', 'failed')),
    step text not null,
    mode text,
    detail jsonb not null default '{}',
    error text,
    attempts integer not null default 1,
    started_at timestamp not null default localtimestamp,
    updated_at timestamp not null default localtimestamp,
    finished_at timestamp
);
