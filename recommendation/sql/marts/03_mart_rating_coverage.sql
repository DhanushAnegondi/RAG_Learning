-- How much rating evidence each language has. A like is a rating of like_rating or more.
create or replace table mart_rating_coverage as
with per_film as (
    select
        ratings.movie_id,
        count(*) as ratings,
        count(*) filter (where ratings.rating >= getvariable('like_rating')) as likes
    from stg_ratings as ratings
    group by ratings.movie_id
)

select
    films.language,
    count(*) as movies,
    count(per_film.movie_id) as movies_with_ratings,
    coalesce(sum(per_film.ratings), 0)::bigint as ratings,
    coalesce(sum(per_film.likes), 0)::bigint as likes,
    coalesce(median(per_film.ratings), 0) as median_ratings_per_rated_film
from mart_movies_clean as films
left join per_film on films.movie_id = per_film.movie_id
group by films.language;
