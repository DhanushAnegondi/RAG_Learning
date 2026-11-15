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
