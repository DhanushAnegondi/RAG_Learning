-- parameters: city
select
    source,
    raw_rows,
    usable_days,
    first_date,
    last_date,
    rejected_days,
    missing_days
from mart_data_quality
where city = %(city)s
order by source;
