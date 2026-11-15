-- Sprint 04: the planning assistant. Schema `agent` holds the tool-call log and LangGraph's own
-- checkpoint and store tables (created by its setup(), found here through search_path).
create schema if not exists agent;

-- Every tool call the assistant makes. call_id = thread id + the model's tool-call id, so a
-- replay after a crash finds the finished call and returns `result` without running it again.
-- attempts counts real executions of the tool's SQL.
create table agent.tool_call (
    call_id text primary key,
    thread_id text not null,
    tool text not null,
    args jsonb not null,
    status text not null check (status in ('running', 'ok', 'error', 'timeout')),
    attempts integer not null default 0,
    row_count integer,
    ms integer,
    error text,
    result jsonb,
    started_at timestamp not null default localtimestamp,
    finished_at timestamp
);

create index tool_call_thread on agent.tool_call (thread_id, started_at);

-- The role tool queries run as (set local role). It cannot log in and can only read the tables
-- granted here and in sql/agent/grant_reader.sql. Roles are cluster-wide, hence the guard.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'weatherwise_reader') then
        create role weatherwise_reader nologin;
    end if;
end
$$;

grant usage on schema public to weatherwise_reader;
grant select on log_forecast, app_model_eval, app_run to weatherwise_reader;
