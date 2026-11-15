-- Empties the warehouse. Only ever run against a *_test database (warehouse.reset checks).
truncate table
raw_actual_daily,
raw_published_hourly,
raw_live_forecast,
raw_user_observation,
log_forecast,
app_model_eval,
app_run;

drop table if exists mart_forecast_error, mart_error_by_lead, mart_model_pairs, mart_data_quality
cascade;

-- The assistant's log and LangGraph's checkpoint and store tables (schema agent), if created.
do $$
declare t record;
begin
    for t in
        select tablename from pg_tables
        where schemaname = 'agent' and tablename not like '%migrations'
    loop
        execute format('truncate table agent.%I cascade', t.tablename);
    end loop;
end
$$;
