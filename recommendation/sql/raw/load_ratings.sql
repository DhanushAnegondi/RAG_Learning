-- Full refresh of MovieLens ratings and the MovieLens -> TMDB id map: a rerun gives the same rows.
delete from raw_ratings;

insert into raw_ratings
select
    source.userid as user_id,
    source.movieid as movielens_id,
    source.rating,
    source.timestamp as rated_at_epoch
from read_csv(
    getvariable('ratings_path'),
    header = true,
    columns = { 'userId': 'bigint', 'movieId': 'bigint', 'rating': 'double', 'timestamp': 'bigint' }
) as source;

delete from raw_links;

insert into raw_links
select
    source.movieid as movielens_id,
    source.imdbid as imdb_id,
    source.tmdbid as tmdb_id
from read_csv(
    getvariable('links_path'),
    header = true,
    columns = { 'movieId': 'bigint', 'imdbId': 'varchar', 'tmdbId': 'bigint' }
) as source;
