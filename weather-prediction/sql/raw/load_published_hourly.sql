-- incoming: temp table filled by warehouse.load. A repeated key in one batch raises and
-- rolls the load back.
insert into raw_published_hourly (city, model, ts_local, lead_days, temp_c)
select
    incoming.city,
    incoming.model,
    incoming.ts_local,
    incoming.lead_days,
    incoming.temp_c
from incoming
on conflict (city, model, ts_local, lead_days) do update
    set
        temp_c = excluded.temp_c,
        loaded_at = localtimestamp
    where raw_published_hourly.temp_c is distinct from excluded.temp_c;
