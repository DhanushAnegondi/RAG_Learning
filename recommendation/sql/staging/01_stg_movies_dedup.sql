-- One row per film id. Blank text, zero runtime and unreadable dates become null (they are
-- missing values, to be filled later, never a reason to drop the row). When the source repeats
-- an id, the row with the most filled-in fields wins; ties go to more votes, then to title and
-- overview, then to every remaining column in turn, so two copies that differ anywhere always
-- rank the same way, whatever order the rows were loaded in.
-- max_imdb_votes is the highest vote count among the copies of an id: the English vote floor
-- looks at it, so a film is not cut because its most complete copy has a stale vote count.
create or replace table stg_movies_dedup as
with normalized as (
    select
        source.id as movie_id,
        nullif(trim(source.tconst), '') as imdb_id,
        nullif(trim(source.title), '') as title,
        nullif(trim(source.original_title), '') as original_title,
        source.original_language as language,
        nullif(trim(source.status), '') as status,
        try_cast(nullif(trim(source.release_date), '') as date) as release_date,
        nullif(source.runtime, 0) as runtime_min,
        nullif(trim(source.overview), '') as overview,
        nullif(trim(source.tagline), '') as tagline,
        nullif(trim(source.genres), '') as genres,
        nullif(trim(source.keywords), '') as keywords,
        nullif(trim(source.directors), '') as directors,
        nullif(trim(source.cast_names), '') as cast_names,
        source.imdb_rating,
        source.imdb_votes,
        source.popularity,
        coalesce(source.adult, false) as is_adult
    from raw_movies as source
),

ranked as (
    select
        normalized.*,
        row_number() over (
            partition by normalized.movie_id
            order by
                (
                    (normalized.title is not null)::int
                    + (normalized.release_date is not null)::int
                    + (normalized.runtime_min is not null)::int
                    + (normalized.overview is not null)::int
                    + (normalized.genres is not null)::int
                    + (normalized.keywords is not null)::int
                    + (normalized.directors is not null)::int
                    + (normalized.cast_names is not null)::int
                    + (normalized.imdb_rating is not null)::int
                ) desc,
                normalized.imdb_votes desc nulls last,
                normalized.title asc nulls last,
                normalized.overview asc nulls last,
                normalized.imdb_id asc nulls last,
                normalized.original_title asc nulls last,
                normalized.language asc nulls last,
                normalized.status asc nulls last,
                normalized.release_date asc nulls last,
                normalized.runtime_min asc nulls last,
                normalized.tagline asc nulls last,
                normalized.genres asc nulls last,
                normalized.keywords asc nulls last,
                normalized.directors asc nulls last,
                normalized.cast_names asc nulls last,
                normalized.imdb_rating asc nulls last,
                normalized.popularity asc nulls last,
                normalized.is_adult asc
        ) as copy_rank,
        max(normalized.imdb_votes) over (partition by normalized.movie_id) as max_imdb_votes
    from normalized
)

select
    ranked.movie_id,
    ranked.imdb_id,
    ranked.title,
    ranked.original_title,
    ranked.language,
    ranked.status,
    ranked.release_date,
    year(ranked.release_date)::integer as release_year,
    ranked.runtime_min,
    ranked.overview,
    ranked.tagline,
    ranked.genres,
    ranked.keywords,
    ranked.directors,
    ranked.cast_names,
    ranked.imdb_rating,
    ranked.imdb_votes,
    ranked.max_imdb_votes,
    ranked.popularity,
    ranked.is_adult
from ranked
where ranked.copy_rank = 1;
