-- parameters: city, today, days. The newest decision given at the gate in the `days` days
-- before today, if any: the gate does not ask again that soon.
select
    today,
    detail ->> 'decision' as decision
from app_run_log
where
    city = %(city)s
    and jsonb_exists(detail, 'decision')
    and today < %(today)s
    and today >= cast(%(today)s as date) - %(days)s
order by today desc
limit 1;
