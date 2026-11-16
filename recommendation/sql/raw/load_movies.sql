-- Full refresh of raw_movies from the landed parquet file: a rerun gives the same rows.
-- Only the two project languages are landed; every other column filter waits for staging.
delete from raw_movies;

insert into raw_movies
select
    source.id,
    source.title,
    source.original_title,
    source.original_language,
    source.status,
    source.release_date,
    source.runtime,
    source.adult,
    source.tconst,
    source.overview,
    source.tagline,
    source.genres,
    source.keywords,
    source.directors,
    source."cast" as cast_names,
    source.averagerating as imdb_rating,
    source.numvotes as imdb_votes,
    source.popularity
from read_parquet(getvariable('movies_path')) as source
where source.original_language in ('en', 'te');
