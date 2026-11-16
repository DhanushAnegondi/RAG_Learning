-- noqa: disable=RF01
-- (sqlfluff cannot resolve the alias of an unpivot; the references below are valid DuckDB)
-- Missing values per language and column: before cleaning (stg_movies) and after
-- (mart_movies_clean). filled_rows counts the fill flags; it must equal missing_before.
create or replace table mart_missing_audit as
with before_wide as (
    select
        staged.language,
        count(*) as total_rows,
        count(*) filter (where staged.title is null) as title,
        count(*) filter (where staged.release_year is null) as release_year,
        count(*) filter (where staged.runtime_min is null) as runtime_min,
        count(*) filter (where staged.genres is null) as genres,
        count(*) filter (where staged.overview is null) as overview,
        count(*) filter (where staged.keywords is null) as keywords,
        count(*) filter (where staged.directors is null) as directors,
        count(*) filter (where staged.cast_names is null) as cast_names,
        count(*) filter (where staged.imdb_rating is null) as imdb_rating,
        count(*) filter (where staged.imdb_votes is null) as imdb_votes
    from stg_movies as staged
    group by staged.language
),

after_wide as (
    select
        cleaned.language,
        count(*) filter (where cleaned.title is null) as title,
        count(*) filter (where cleaned.release_year is null) as release_year,
        count(*) filter (where cleaned.runtime_min is null) as runtime_min,
        count(*) filter (where cleaned.genres is null) as genres,
        count(*) filter (where cleaned.overview is null) as overview,
        count(*) filter (where cleaned.keywords is null) as keywords,
        count(*) filter (where cleaned.directors is null) as directors,
        count(*) filter (where cleaned.cast_names is null) as cast_names,
        count(*) filter (where cleaned.imdb_rating is null) as imdb_rating,
        count(*) filter (where cleaned.imdb_votes is null) as imdb_votes
    from mart_movies_clean as cleaned
    group by cleaned.language
),

flags_wide as (
    select
        cleaned.language,
        count(*) filter (where cleaned.title_filled) as title,
        count(*) filter (where cleaned.release_year_filled) as release_year,
        count(*) filter (where cleaned.runtime_min_filled) as runtime_min,
        count(*) filter (where cleaned.genres_filled) as genres,
        count(*) filter (where cleaned.overview_filled) as overview,
        count(*) filter (where cleaned.keywords_filled) as keywords,
        count(*) filter (where cleaned.directors_filled) as directors,
        count(*) filter (where cleaned.cast_names_filled) as cast_names,
        count(*) filter (where cleaned.imdb_rating_filled) as imdb_rating,
        count(*) filter (where cleaned.imdb_votes_filled) as imdb_votes
    from mart_movies_clean as cleaned
    group by cleaned.language
),

before_long as (
    select
        unpivoted.language,
        unpivoted.total_rows,
        unpivoted.column_name,
        unpivoted.missing_before
    from before_wide unpivot (
        missing_before for column_name in (
            title, release_year, runtime_min, genres, overview,
            keywords, directors, cast_names, imdb_rating, imdb_votes
        )
    ) as unpivoted
),

after_long as (
    select
        unpivoted.language,
        unpivoted.column_name,
        unpivoted.missing_after
    from after_wide unpivot (
        missing_after for column_name in (
            title, release_year, runtime_min, genres, overview,
            keywords, directors, cast_names, imdb_rating, imdb_votes
        )
    ) as unpivoted
),

flags_long as (
    select
        unpivoted.language,
        unpivoted.column_name,
        unpivoted.filled_rows
    from flags_wide unpivot (
        filled_rows for column_name in (
            title, release_year, runtime_min, genres, overview,
            keywords, directors, cast_names, imdb_rating, imdb_votes
        )
    ) as unpivoted
)

select
    before_long.language,
    before_long.column_name,
    before_long.total_rows,
    before_long.missing_before,
    after_long.missing_after,
    flags_long.filled_rows,
    round(100.0 * before_long.missing_before / before_long.total_rows, 1) as missing_before_pct
from before_long
inner join after_long
    on
        before_long.language = after_long.language
        and before_long.column_name = after_long.column_name
inner join flags_long
    on
        before_long.language = flags_long.language
        and before_long.column_name = flags_long.column_name;
