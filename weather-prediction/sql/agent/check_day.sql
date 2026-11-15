-- tool check_day. parameters: city, day. What was forecast for a day the user entered a reading
-- for, at every lead, against that reading. error = forecast - observed.
select
    variable,
    lead_days,
    kind,
    issued_on,
    inside_range,
    cast(round(cast(observed_c as numeric), 1) as double precision) as observed_c,
    cast(round(cast(pred_c as numeric), 1) as double precision) as weatherwise_c,
    cast(round(cast(lo_c as numeric), 1) as double precision) as range_low_end_c,
    cast(round(cast(hi_c as numeric), 1) as double precision) as range_high_end_c,
    cast(round(cast(published_c as numeric), 1) as double precision) as published_c,
    cast(round(cast(our_error_c as numeric), 1) as double precision) as weatherwise_error_c,
    cast(round(cast(published_error_c as numeric), 1) as double precision) as published_error_c
from mart_verification
where city = %(city)s and date = %(day)s
order by variable, lead_days;
