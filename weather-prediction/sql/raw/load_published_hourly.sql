-- Fail loudly on duplicate keys in one batch: insert or replace would keep one silently.
select error('duplicate key in incoming batch for raw_published_hourly')
from incoming
group by city, ts_local, lead_days
having count(*) > 1;

-- incoming: DataFrame registered by warehouse.load
insert or replace into raw_published_hourly (city, ts_local, lead_days, temp_c, loaded_at)
select
    city,
    cast(ts_local as timestamp) as ts_local,
    cast(lead_days as integer) as lead_days,
    temp_c,
    current_timestamp as loaded_at
from incoming;
