select
    city,
    max(issued_on) as issued_on
from log_forecast
where kind = 'live'
group by city;
