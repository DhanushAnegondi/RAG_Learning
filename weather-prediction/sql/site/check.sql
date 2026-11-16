-- parameters: city, date
select
    variable,
    lead_days,
    kind,
    issued_on,
    method,
    observed_c,
    era5_c,
    inside_range,
    cast(round(cast(pred_c as numeric), 2) as double precision) as pred_c,
    cast(round(cast(lo_c as numeric), 2) as double precision) as lo_c,
    cast(round(cast(hi_c as numeric), 2) as double precision) as hi_c,
    cast(round(cast(published_c as numeric), 2) as double precision) as published_c,
    cast(round(cast(our_error_c as numeric), 2) as double precision) as our_error_c,
    cast(round(cast(published_error_c as numeric), 2) as double precision) as published_error_c
from mart_verification
where city = %(city)s and date = %(day)s
order by variable, lead_days;
