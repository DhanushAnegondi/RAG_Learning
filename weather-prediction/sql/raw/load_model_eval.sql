-- The leaderboard is rebuilt per city on every run. A repeated key in the batch violates the
-- primary key and rolls the load back.
delete from app_model_eval
where city in (select incoming.city from incoming);

insert into app_model_eval (
    city, variable, lead_days, method, cv_mae_c, test_mae_c, test_days, chosen, coverage_pct
)
select
    incoming.city,
    incoming.variable,
    incoming.lead_days,
    incoming.method,
    incoming.cv_mae_c,
    incoming.test_mae_c,
    incoming.test_days,
    incoming.chosen,
    incoming.coverage_pct
from incoming;
