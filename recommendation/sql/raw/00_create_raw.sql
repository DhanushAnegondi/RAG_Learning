-- Raw layer: source rows as landed, English and Telugu only. No cleaning here.
create table if not exists raw_movies (
    id bigint,
    title varchar,
    original_title varchar,
    original_language varchar,
    status varchar,
    release_date varchar,
    runtime bigint,
    adult boolean,
    tconst varchar,
    overview varchar,
    tagline varchar,
    genres varchar,
    keywords varchar,
    directors varchar,
    cast_names varchar,
    imdb_rating double,
    imdb_votes bigint,
    popularity double
);

create table if not exists raw_ratings (
    user_id bigint,
    movielens_id bigint,
    rating double,
    rated_at_epoch bigint
);

create table if not exists raw_links (
    movielens_id bigint,
    imdb_id varchar,
    tmdb_id bigint
);
