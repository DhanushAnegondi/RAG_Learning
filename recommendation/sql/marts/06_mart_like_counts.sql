-- Likes per film before each cutoff, from every user (not a sample): the popularity baseline.
-- A like is a rating of like_rating or more. Ratings at or after a cutoff are never counted.
-- Films nobody rated have no row; Python treats them as zero.
create or replace table mart_like_counts as
select
    ratings.movie_id,
    count(*) filter (
        where ratings.rating >= getvariable('like_rating') and ratings.rated_at < split.val_start
    ) as likes_before_val,
    count(*) filter (
        where ratings.rating >= getvariable('like_rating') and ratings.rated_at < split.test_start
    ) as likes_before_test
from stg_ratings as ratings
cross join mart_split as split
group by ratings.movie_id;
