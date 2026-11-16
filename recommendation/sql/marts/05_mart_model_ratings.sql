-- The ratings the models need, so Python never loads all of them:
--   is_cf_user   a fixed sample (user_id % cf_user_mod = 0) that item-item similarity and
--                popularity are learned from;
--   is_eval_user anyone who rated at or after val_start; these users can be scored, and all
--                of their ratings are kept so their earlier likes form the profile.
create or replace table mart_model_ratings as
with late_users as (
    select distinct ratings.user_id
    from stg_ratings as ratings
    cross join mart_split as split
    where ratings.rated_at >= split.val_start
),

flagged as (
    select
        ratings.user_id,
        ratings.movie_id,
        ratings.rating,
        ratings.rated_at,
        ratings.user_id % getvariable('cf_user_mod') = 0 as is_cf_user,
        late_users.user_id is not null as is_eval_user
    from stg_ratings as ratings
    left join late_users on ratings.user_id = late_users.user_id
)

select
    flagged.user_id,
    flagged.movie_id,
    flagged.rating,
    flagged.rated_at,
    flagged.is_cf_user,
    flagged.is_eval_user
from flagged
where flagged.is_cf_user or flagged.is_eval_user;
