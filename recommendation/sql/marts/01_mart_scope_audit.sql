-- Where every landed row went:
-- kept = landed_rows - duplicate_rows - adult_titles - below_vote_floor.
create or replace table mart_scope_audit as
with landed as (
    select
        source.original_language as language,
        count(*) as landed_rows,
        count(distinct source.id) as distinct_films
    from raw_movies as source
    group by source.original_language
),

films as (
    select
        dedup.language,
        count(*) filter (where dedup.is_adult) as adult_titles,
        count(*) filter (
            where
            not dedup.is_adult
            and dedup.language <> 'te'
            and (dedup.max_imdb_votes is null or dedup.max_imdb_votes < getvariable('en_min_votes'))
        ) as below_vote_floor
    from stg_movies_dedup as dedup
    group by dedup.language
),

kept as (
    select
        staged.language,
        count(*) as kept
    from stg_movies as staged
    group by staged.language
)

select
    landed.language,
    landed.landed_rows,
    landed.landed_rows - landed.distinct_films as duplicate_rows,
    films.adult_titles,
    films.below_vote_floor,
    coalesce(kept.kept, 0) as kept
from landed
inner join films on landed.language = films.language
left join kept on landed.language = kept.language;
