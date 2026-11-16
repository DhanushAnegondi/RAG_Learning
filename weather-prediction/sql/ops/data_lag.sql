-- parameters: city, today, window. lag_days: days between yesterday and the newest usable
-- actual (0 = up to date). recent_days: usable days among the last `window` calendar days up
-- to that newest one (fewer than `window` = a hole the models cannot forecast across).
with newest as (
    select max(date) as last_day
    from stg_actual_daily
    where city = %(city)s
)

select
    (cast(%(today)s as date) - 1) - newest.last_day as lag_days,
    (
        select count(*)
        from stg_actual_daily as recent
        where recent.city = %(city)s and recent.date > newest.last_day - %(window)s
    ) as recent_days
from newest;
