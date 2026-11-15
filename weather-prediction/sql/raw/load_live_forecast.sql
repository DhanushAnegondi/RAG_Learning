-- incoming: temp table filled by warehouse.load, with an issued_on column. A repeated key in
-- one batch raises and rolls the load back.
insert into raw_live_forecast (city, model, issued_on, date, tmax_c, tmin_c, precip_mm)
select
    incoming.city,
    incoming.model,
    incoming.issued_on,
    incoming.date,
    incoming.tmax_c,
    incoming.tmin_c,
    incoming.precip_mm
from incoming
on conflict (city, model, issued_on, date) do update
    set
        tmax_c = excluded.tmax_c,
        tmin_c = excluded.tmin_c,
        precip_mm = excluded.precip_mm,
        loaded_at = localtimestamp;
