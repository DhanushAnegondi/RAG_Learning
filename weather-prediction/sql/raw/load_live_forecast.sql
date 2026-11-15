-- Fail loudly on duplicate keys in one batch: insert or replace would keep one silently.
select error('duplicate key in incoming batch for raw_live_forecast')
from incoming
group by city, issued_on, date
having count(*) > 1;

-- incoming: DataFrame registered by warehouse.load, with an issued_on column
insert or replace into raw_live_forecast (
    city, issued_on, date, tmax_c, tmin_c, precip_mm, loaded_at
)
select
    city,
    cast(issued_on as date) as issued_on,
    cast(date as date) as date,
    tmax_c,
    tmin_c,
    precip_mm,
    current_timestamp as loaded_at
from incoming;
