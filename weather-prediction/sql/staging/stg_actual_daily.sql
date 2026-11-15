-- Observed (ERA5 reanalysis) daily values; days without a max temperature are unusable.
create or replace view stg_actual_daily as
with source as (
    select * from raw_actual_daily
)

select
    source.city,
    source.date,
    source.tmax_c,
    source.tmin_c,
    source.precip_mm
from source
where source.tmax_c is not null and source.tmin_c is not null;
