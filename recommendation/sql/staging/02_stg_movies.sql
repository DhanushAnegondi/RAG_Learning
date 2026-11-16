-- Project scope, applied once and counted in mart_scope_audit:
--   every Telugu film is kept, however few votes it has;
--   an English film needs at least en_min_votes IMDb votes on its best-voted copy (the source
--   lists 230k English titles);
--   adult titles are left out.
-- Scope is about which films the project covers. It never looks at whether a field is missing.
create or replace table stg_movies as
select
    films.movie_id,
    films.imdb_id,
    films.title,
    films.original_title,
    films.language,
    films.status,
    films.release_date,
    films.release_year,
    films.runtime_min,
    films.overview,
    films.tagline,
    films.genres,
    films.keywords,
    films.directors,
    films.cast_names,
    films.imdb_rating,
    films.imdb_votes,
    films.popularity
from stg_movies_dedup as films
where
    not films.is_adult
    and (films.language = 'te' or films.max_imdb_votes >= getvariable('en_min_votes'));
