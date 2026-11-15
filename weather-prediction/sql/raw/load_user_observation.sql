-- incoming: one row per city and date; typing a day again replaces the earlier entry
insert into raw_user_observation (city, date, tmax_c, tmin_c, note, entered_at)
select
    incoming.city,
    incoming.date,
    incoming.tmax_c,
    incoming.tmin_c,
    incoming.note,
    incoming.entered_at
from incoming
on conflict (city, date) do update
    set
        tmax_c = excluded.tmax_c,
        tmin_c = excluded.tmin_c,
        note = excluded.note,
        entered_at = excluded.entered_at;
