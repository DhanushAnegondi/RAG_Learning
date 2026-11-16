-- MovieLens ratings re-keyed to the film id used everywhere else (TMDB id), in-scope films only.
-- MovieLens sometimes has two ids for one film. The user's EARLIEST rating of the film is kept,
-- with its time, so their history stays in the past (the film counts as seen) and a later
-- re-rating under the second id cannot move a like across a cutoff. Two ratings at the same
-- second go to the lower MovieLens id, so the choice is the same on every run.
create or replace table stg_ratings as
with mapped as (
    select
        ratings.user_id,
        ratings.movielens_id,
        links.tmdb_id as movie_id,
        ratings.rating,
        make_timestamp(ratings.rated_at_epoch * 1000000) as rated_at
    from raw_ratings as ratings
    inner join raw_links as links on ratings.movielens_id = links.movielens_id
    inner join stg_movies as films on links.tmdb_id = films.movie_id
),

ranked as (
    select
        mapped.user_id,
        mapped.movie_id,
        mapped.rating,
        mapped.rated_at,
        row_number() over (
            partition by mapped.user_id, mapped.movie_id
            order by mapped.rated_at asc, mapped.movielens_id asc
        ) as pick
    from mapped
)

select
    ranked.user_id,
    ranked.movie_id,
    ranked.rating,
    ranked.rated_at
from ranked
where ranked.pick = 1;
