-- Hindcasts are replayed from scratch each run. A live row is written once: the first
-- forecast issued for a city, day and variable on an issue day is the one that is kept.
delete from log_forecast
where
    kind = 'hindcast'
    and city in (
        select incoming.city from incoming
        where incoming.kind = 'hindcast'
    );

insert into log_forecast (
    city, kind, issued_on, date, variable, lead_days, pred_c, lo_c, hi_c, published_c, method,
    logged_at
)
select
    incoming.city,
    incoming.kind,
    incoming.issued_on,
    incoming.date,
    incoming.variable,
    incoming.lead_days,
    incoming.pred_c,
    incoming.lo_c,
    incoming.hi_c,
    incoming.published_c,
    incoming.method,
    incoming.logged_at
from incoming
on conflict (city, kind, issued_on, date, variable) do update
    set
        lead_days = excluded.lead_days,
        pred_c = excluded.pred_c,
        lo_c = excluded.lo_c,
        hi_c = excluded.hi_c,
        published_c = excluded.published_c,
        method = excluded.method,
        logged_at = excluded.logged_at
    where log_forecast.kind = 'hindcast';
