-- Observed (ERA5 reanalysis) daily values. Cleaning: a day needs both max and min, inside
-- -60..60 C, with max >= min. Rejected rows are listed in stg_quality_issues.
-- A null fails the range test, so missing values are excluded by the same condition.
drop view if exists stg_actual_daily cascade;

create view stg_actual_daily as
select
    source.city,
    source.date,
    source.tmax_c,
    source.tmin_c,
    source.precip_mm
from raw_actual_daily as source
where
    source.tmax_c between -60 and 60
    and source.tmin_c between -60 and 60
    and source.tmax_c >= source.tmin_c;
