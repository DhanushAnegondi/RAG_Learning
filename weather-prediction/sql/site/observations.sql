-- parameters: city
select
    date,
    tmax_c,
    tmin_c,
    note,
    entered_at
from raw_user_observation
where city = %(city)s
order by date desc;
