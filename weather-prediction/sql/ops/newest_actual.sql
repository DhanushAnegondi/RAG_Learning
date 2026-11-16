-- parameters: city. The newest day any actual is loaded for.
select max(date) as newest
from raw_actual_daily
where city = %(city)s;
