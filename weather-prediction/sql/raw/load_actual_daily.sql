-- Fail loudly on duplicate keys in one batch: insert or replace would keep one silently.
select error('duplicate key in incoming batch for raw_actual_daily')
from incoming
group by city, date
having count(*) > 1;

-- incoming: DataFrame registered by warehouse.load
insert or replace into raw_actual_daily (city, date, tmax_c, tmin_c, precip_mm, loaded_at)
select
    city,
    cast(date as date) as date,
    tmax_c,
    tmin_c,
    precip_mm,
    current_timestamp as loaded_at
from incoming;
