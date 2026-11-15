-- incoming: temp table filled by warehouse.load; it carries the same primary key, so a key
-- repeated inside one batch fails at copy time and the whole load rolls back.
-- loaded_at moves only when a value really changed.
insert into raw_actual_daily (city, date, tmax_c, tmin_c, precip_mm)
select
    incoming.city,
    incoming.date,
    incoming.tmax_c,
    incoming.tmin_c,
    incoming.precip_mm
from incoming
on conflict (city, date) do update
    set
        tmax_c = excluded.tmax_c,
        tmin_c = excluded.tmin_c,
        precip_mm = excluded.precip_mm,
        loaded_at = localtimestamp
    where
    (raw_actual_daily.tmax_c, raw_actual_daily.tmin_c, raw_actual_daily.precip_mm)
    is distinct from (excluded.tmax_c, excluded.tmin_c, excluded.precip_mm);
