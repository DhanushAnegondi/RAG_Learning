-- Time split, counted back in whole months from the day of the last rating:
--   ratings before val_start             -> fit the models used to pick the blend weight
--   val_start <= rating < test_start     -> validation (pick the blend weight)
--   rating >= test_start                 -> test (final numbers only)
create or replace table mart_split as
with bounds as (
    select max(ratings.rated_at) as last_rating
    from stg_ratings as ratings
)

select
    bounds.last_rating,
    (
        date_trunc('day', bounds.last_rating) - to_months(getvariable('test_months'))
    )::timestamp as test_start,
    (
        date_trunc('day', bounds.last_rating)
        - to_months(getvariable('test_months') + getvariable('val_months'))
    )::timestamp as val_start
from bounds;
