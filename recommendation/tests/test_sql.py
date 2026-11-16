"""SQL stages on an in-memory DuckDB, fed from small files written in tmp_path."""

import duckdb
import pandas as pd
import pytest

from cinebridge import warehouse

RAW_COLUMNS = [
    "id",
    "title",
    "original_title",
    "original_language",
    "status",
    "release_date",
    "runtime",
    "adult",
    "tconst",
    "overview",
    "tagline",
    "genres",
    "keywords",
    "directors",
    "cast",
    "averageRating",
    "numVotes",
    "popularity",
]


def raw(movie_id: int, **over) -> dict:
    row = {
        "id": movie_id,
        "title": f"Film {movie_id}",
        "original_title": f"Film {movie_id}",
        "original_language": "en",
        "status": "Released",
        "release_date": "2001-05-20",
        "runtime": 100,
        "adult": False,
        "tconst": f"tt{movie_id}",
        "overview": "a story",
        "tagline": None,
        "genres": "Drama",
        "keywords": "k",
        "directors": "D",
        "cast": "A",
        "averageRating": 7.0,
        "numVotes": 5000,
        "popularity": 1.0,
    }
    assert set(over) <= set(row)
    row.update(over)
    return row


def land(tmp_path, rows: list[dict], name: str = "movies.parquet"):
    """Write rows as a parquet file with the source's column names and types."""
    path = tmp_path / name
    df = pd.DataFrame(rows, columns=RAW_COLUMNS).astype(object)  # noqa: F841 (read by duckdb)
    types = {
        "id": "bigint",
        "runtime": "bigint",
        "numVotes": "bigint",
        "adult": "boolean",
        "averageRating": "double",
        "popularity": "double",
    }
    cols = ", ".join(f'cast("{c}" as {types.get(c, "varchar")}) as "{c}"' for c in RAW_COLUMNS)
    duckdb.connect().execute(
        f"copy (select {cols} from df) to '{path.as_posix()}' (format parquet)"
    ).fetchall()
    return path


def staged(tmp_path, rows: list[dict], en_min_votes: int = 1000):
    con = warehouse.connect()
    warehouse.load_movies(con, land(tmp_path, rows))
    warehouse.build_staging(con, en_min_votes=en_min_votes)
    return con


def build_marts(con, **over) -> None:
    args = {"test_months": 12, "val_months": 12, "cf_user_mod": 1, "like_rating": 4.0, **over}
    warehouse.build_marts(con, **args)


def ids(con, table: str = "stg_movies") -> list[int]:
    return [r[0] for r in con.execute(f"select movie_id from {table} order by 1").fetchall()]


def test_load_movies_keeps_only_english_and_telugu(tmp_path):
    con = warehouse.connect()
    path = land(
        tmp_path,
        [raw(1), raw(2, original_language="te"), raw(3, original_language="hi")],
    )
    assert warehouse.load_movies(con, path) == 2
    langs = con.execute("select original_language from raw_movies order by id").fetchall()
    assert langs == [("en",), ("te",)]


def test_load_movies_rerun_gives_same_rows(tmp_path):
    con = warehouse.connect()
    path = land(tmp_path, [raw(1), raw(2, original_language="te")])
    first = warehouse.load_movies(con, path)
    second = warehouse.load_movies(con, path)
    assert first == second == 2


def test_staging_keeps_telugu_below_the_english_vote_floor(tmp_path):
    con = staged(
        tmp_path,
        [
            raw(1, numVotes=999),
            raw(2, numVotes=1000),
            raw(3, original_language="te", numVotes=3),
            raw(4, original_language="te", numVotes=None),
        ],
    )
    assert ids(con) == [2, 3, 4]


def test_staging_excludes_adult_titles_and_treats_null_adult_as_not_adult(tmp_path):
    con = staged(tmp_path, [raw(1, adult=True), raw(2, adult=None), raw(3)])
    assert ids(con) == [2, 3]


def test_staging_dedup_keeps_the_most_complete_row(tmp_path):
    con = staged(
        tmp_path,
        [
            raw(7, overview=None, genres=None, title="thin copy"),
            raw(7, title="full copy"),
            raw(7, overview=None, title="middle copy"),
        ],
    )
    assert con.execute("select movie_id, title from stg_movies").fetchall() == [(7, "full copy")]


def test_staging_cuts_an_english_film_with_no_votes(tmp_path):
    con = staged(tmp_path, [raw(1, numVotes=None), raw(2)])
    assert ids(con) == [2]


def test_vote_floor_looks_at_the_highest_vote_count_among_the_copies_of_an_id(tmp_path):
    """The kept copy (most complete) has 50 votes; another copy of the id has 5000."""
    con = staged(
        tmp_path,
        [
            raw(5, numVotes=50, title="complete copy"),
            raw(5, numVotes=5000, overview=None, title="thin copy"),
            raw(6, numVotes=50),
            raw(6, numVotes=60, overview=None),
        ],
    )
    assert con.execute("select movie_id, title, imdb_votes from stg_movies").fetchall() == [
        (5, "complete copy", 50)
    ]
    warehouse.run_sql_file(con, warehouse.SQL_DIR / "marts" / "01_mart_scope_audit.sql")
    rows = con.execute(
        "select landed_rows, duplicate_rows, below_vote_floor, kept from mart_scope_audit"
    ).fetchall()
    assert rows == [(4, 2, 1, 1)]  # film 6: both copies are under the floor


def test_dedup_completeness_beats_votes_and_title(tmp_path):
    full = raw(7, title="zzz full", numVotes=2000)
    thin = raw(7, title="aaa thin", overview=None, numVotes=99999)
    for order in ([full, thin], [thin, full]):
        con = staged(tmp_path, order)
        assert con.execute("select title from stg_movies").fetchall() == [("zzz full",)]


def test_dedup_equal_completeness_goes_to_more_votes_then_to_title(tmp_path):
    votes = [raw(7, title="a low votes", numVotes=5000), raw(7, title="z high", numVotes=9000)]
    titles = [raw(8, title="b second", numVotes=5000), raw(8, title="a first", numVotes=5000)]
    for pair, want in ((votes, "z high"), (titles, "a first")):
        for order in (pair, pair[::-1]):
            con = staged(tmp_path, order)
            assert con.execute("select title from stg_movies").fetchall() == [(want,)]


# (raw column, stg column, lower value, higher value): two copies that agree on everything
# ranked before this column and differ only here. The copy with the lower value must win,
# whichever order the rows were loaded in.
TIE_BREAKERS = [
    ("tconst", "imdb_id", "tt1", "tt2"),
    ("original_title", "original_title", "a orig", "b orig"),
    ("original_language", "language", "en", "te"),
    ("status", "status", "Planned", "Released"),
    ("release_date", "release_date", "1999-01-01", "2001-01-01"),
    ("runtime", "runtime_min", 90, 120),
    ("tagline", "tagline", "a tag", "b tag"),
    ("genres", "genres", "Action", "Drama"),
    ("keywords", "keywords", "k1", "k2"),
    ("directors", "directors", "D1", "D2"),
    ("cast", "cast_names", "A1", "A2"),
    ("averageRating", "imdb_rating", 6.0, 8.0),
    ("popularity", "popularity", 1.0, 9.0),
]


@pytest.mark.parametrize(("source", "target", "low", "high"), TIE_BREAKERS)
def test_dedup_tie_never_depends_on_the_order_rows_were_loaded(tmp_path, source, target, low, high):
    a, b = raw(7, **{source: low}), raw(7, **{source: high})
    picked = []
    for order in ([a, b], [b, a]):
        con = staged(tmp_path, order)
        picked.append(con.execute(f"select {target} from stg_movies").fetchall())
    assert picked[0] == picked[1]
    assert str(picked[0][0][0]) == str(low)


def test_dedup_tie_between_an_adult_and_a_non_adult_copy_keeps_the_non_adult_one(tmp_path):
    a, b = raw(7, adult=False), raw(7, adult=True)
    for order in ([a, b], [b, a]):
        assert ids(staged(tmp_path, order)) == [7]


def test_every_blank_text_field_becomes_null(tmp_path):
    con = staged(
        tmp_path, [raw(1, title=" ", original_title="", tconst="  ", tagline="", status=" ")]
    )
    row = con.execute(
        "select title, original_title, imdb_id, tagline, status from stg_movies"
    ).fetchall()
    assert row == [(None,) * 5]


def test_staging_turns_blanks_zero_runtime_and_bad_dates_into_null_but_keeps_the_row(tmp_path):
    con = staged(
        tmp_path,
        [
            raw(
                1,
                overview="   ",
                genres="",
                keywords=" ",
                directors="",
                cast="",
                runtime=0,
                release_date="not a date",
            )
        ],
    )
    row = con.execute(
        "select overview, genres, keywords, directors, cast_names, runtime_min,"
        " release_date, release_year from stg_movies"
    ).fetchall()
    assert row == [(None,) * 8]


def test_staging_reads_release_year_from_the_date(tmp_path):
    con = staged(tmp_path, [raw(1, release_date="1999-12-31")])
    assert con.execute("select release_year from stg_movies").fetchall() == [(1999,)]


def test_scope_audit_counts_add_up(tmp_path):
    con = staged(
        tmp_path,
        [
            raw(1),
            raw(1),  # duplicate id
            raw(2, adult=True),
            raw(3, numVotes=10),  # below floor
            raw(4, original_language="te", numVotes=10),
            raw(5, original_language="te", adult=True),
        ],
    )
    warehouse.run_sql_file(con, warehouse.SQL_DIR / "marts" / "01_mart_scope_audit.sql")
    rows = con.execute(
        "select language, landed_rows, duplicate_rows, adult_titles, below_vote_floor, kept"
        " from mart_scope_audit order by language"
    ).fetchall()
    assert rows == [("en", 4, 1, 1, 1, 1), ("te", 2, 0, 1, 0, 1)]


def load_ratings(con, tmp_path, ratings: str, links: str) -> int:
    rpath, lpath = tmp_path / "ratings.csv", tmp_path / "links.csv"
    rpath.write_text("userId,movieId,rating,timestamp\n" + ratings, encoding="utf-8")
    lpath.write_text("movieId,imdbId,tmdbId\n" + links, encoding="utf-8")
    return warehouse.load_ratings(con, rpath, lpath)


def test_ratings_map_to_tmdb_ids_and_drop_out_of_scope_movies(tmp_path):
    con = staged(tmp_path, [raw(10), raw(20, original_language="te", numVotes=1)])
    n = load_ratings(
        con,
        tmp_path,
        "1,100,4.0,1000000000\n1,200,5.0,1000000100\n2,300,3.0,1000000200\n2,400,2.0,1000000300\n",
        "100,0000010,10\n200,0000020,20\n300,0000030,30\n400,0000040,\n",
    )
    assert n == 4
    warehouse.build_staging(con, en_min_votes=1000)
    rows = con.execute(
        "select user_id, movie_id, rating from stg_ratings order by user_id, movie_id"
    ).fetchall()
    assert rows == [(1, 10, 4.0), (1, 20, 5.0)]


def one_film_two_ids(con, tmp_path, ratings: str):
    load_ratings(con, tmp_path, ratings, "100,0000010,10\n101,0000011,10\n")
    warehouse.build_staging(con, en_min_votes=1000)
    return con.execute("select user_id, movie_id, rating, rated_at from stg_ratings").fetchall()


@pytest.mark.parametrize(
    ("earlier", "later"),
    [("2.0", "5.0"), ("5.0", "2.0")],
    ids=["later is higher", "later is lower"],
)
def test_two_movielens_ids_for_one_film_keep_the_earliest_rating_and_its_time(
    tmp_path, earlier, later
):
    """The earliest rating keeps the user's history in the past and marks the film as seen."""
    con = staged(tmp_path, [raw(10)])
    lines = f"1,100,{earlier},1000000000\n1,101,{later},1000009999\n"
    rows = one_film_two_ids(con, tmp_path, lines)
    assert len(rows) == 1
    assert rows[0][:3] == (1, 10, float(earlier))
    assert rows[0][3] == pd.Timestamp(1000000000, unit="s").to_pydatetime()


def test_two_movielens_ids_rated_at_the_same_second_keep_the_lower_movielens_id(tmp_path):
    for lines in (
        "1,100,3.0,1000000000\n1,101,5.0,1000000000\n",
        "1,101,5.0,1000000000\n1,100,3.0,1000000000\n",
    ):
        con = staged(tmp_path, [raw(10)])
        assert one_film_two_ids(con, tmp_path, lines)[0][2] == 3.0


def test_ratings_rerun_gives_same_rows(tmp_path):
    con = staged(tmp_path, [raw(10)])
    first = load_ratings(con, tmp_path, "1,100,4.0,1000000000\n", "100,0000010,10\n")
    second = load_ratings(con, tmp_path, "1,100,4.0,1000000000\n", "100,0000010,10\n")
    assert first == second == 1
    assert con.execute("select count(*) from raw_links").fetchall() == [(1,)]


def clean_frame(con) -> pd.DataFrame:
    """A stand-in for clean.py: fill every gap so the audit has an 'after' side."""
    df = con.execute("select * from stg_movies order by movie_id").df()
    for col in ("title", "genres", "overview", "keywords", "directors", "cast_names"):
        df[f"{col}_filled"] = df[col].isna()
        df[col] = df[col].fillna("x")
    for col, value in (("release_year", 2000), ("runtime_min", 90)):
        df[f"{col}_filled"] = df[col].isna()
        df[col] = df[col].fillna(value).astype("int64")
    df["imdb_rating_filled"] = df["imdb_rating"].isna()
    df["imdb_rating"] = df["imdb_rating"].fillna(6.0)
    df["imdb_votes_filled"] = df["imdb_votes"].isna()
    df["imdb_votes"] = df["imdb_votes"].fillna(0).astype("int64")
    df["genres_fill_method"] = "observed"
    df["score"] = 6.0
    return df


def test_missing_audit_reports_every_column_with_its_own_counts_and_a_gap_left_after(tmp_path):
    con = staged(
        tmp_path,
        [
            raw(1, keywords=None, genres=None),
            raw(
                2,
                keywords=None,
                directors=None,
                cast=None,
                release_date="bad",
                runtime=0,
                averageRating=None,
            ),
            raw(3, original_language="te", numVotes=None, title=None),
        ],
    )
    df = clean_frame(con)
    df["keywords"] = df["keywords"].astype(object)
    df.loc[df["movie_id"] == 1, "keywords"] = None  # a gap the fill missed
    df["release_year"] = df["release_year"].astype("float64")
    df.loc[df["movie_id"] == 2, "release_year"] = None  # another one
    df["genres"] = df["genres"].astype(object)
    df.loc[df["movie_id"] == 3, "genres"] = None  # and one in a column that was never missing
    assert warehouse.write_clean(con, df) == 3
    build_marts(con)
    rows = con.execute(
        "select language, column_name, total_rows, missing_before, missing_after, filled_rows,"
        " missing_before_pct from mart_missing_audit"
    ).fetchall()
    got = {(lang, col): (n, b, a, f, pct) for lang, col, n, b, a, f, pct in rows}
    assert len(got) == 20
    en = {col: v for (lang, col), v in got.items() if lang == "en"}
    # (total, before, after, filled, pct): en has films 1 and 2
    assert en == {
        "title": (2, 0, 0, 0, 0.0),
        "release_year": (2, 1, 1, 1, 50.0),  # film 2: bad date; left unfilled above
        "runtime_min": (2, 1, 0, 1, 50.0),  # film 2: runtime 0
        "genres": (2, 1, 0, 1, 50.0),  # film 1; its overview was observed
        "overview": (2, 0, 0, 0, 0.0),
        "keywords": (2, 2, 1, 2, 100.0),  # films 1, 2; film 1 left unfilled above
        "directors": (2, 1, 0, 1, 50.0),
        "cast_names": (2, 1, 0, 1, 50.0),
        "imdb_rating": (2, 1, 0, 1, 50.0),
        "imdb_votes": (2, 0, 0, 0, 0.0),
    }
    te = {col: v for (lang, col), v in got.items() if lang == "te"}
    assert te["title"] == (1, 1, 0, 1, 100.0)
    assert te["genres"] == (1, 0, 1, 0, 0.0)  # missing after, never before: no flag
    assert te["imdb_votes"] == (1, 1, 0, 1, 100.0)
    assert te["keywords"] == (1, 0, 0, 0, 0.0)


def test_write_clean_refuses_a_frame_that_lost_or_gained_rows(tmp_path):
    con = staged(tmp_path, [raw(1), raw(2)])
    df = clean_frame(con)
    with pytest.raises(ValueError, match="row"):
        warehouse.write_clean(con, df.iloc[:1])
    with pytest.raises(ValueError, match="row"):
        warehouse.write_clean(con, pd.concat([df, df.iloc[:1]]))


def test_write_clean_refuses_a_frame_with_different_ids(tmp_path):
    con = staged(tmp_path, [raw(1), raw(2)])
    df = clean_frame(con)
    df.loc[df["movie_id"] == 2, "movie_id"] = 99
    with pytest.raises(ValueError, match="movie_id"):
        warehouse.write_clean(con, df)


def coverage_setup(tmp_path, like_rating: float):
    con = staged(
        tmp_path,
        [
            raw(10),
            raw(11),
            raw(12),
            raw(20, original_language="te"),
            raw(21, original_language="te"),
        ],
    )
    load_ratings(
        con,
        tmp_path,
        # film 10: 4.0, 3.5, 4.5; film 11: 4.0; film 12 unrated; te film 20: 5.0, 3.0; te 21: 4.0
        "1,100,4.0,1000000000\n2,100,3.5,1000000000\n3,100,4.5,1000000000\n"
        "1,110,4.0,1000000000\n1,200,5.0,1000000000\n2,200,3.0,1000000000\n"
        "3,210,4.0,1000000000\n",
        "100,0000010,10\n110,0000011,11\n120,0000012,12\n200,0000020,20\n210,0000021,21\n",
    )
    warehouse.build_staging(con, en_min_votes=1000)
    warehouse.write_clean(con, clean_frame(con))
    build_marts(con, like_rating=like_rating)
    return con


COVERAGE_SQL = (
    "select language, movies, movies_with_ratings, ratings, likes, median_ratings_per_rated_film"
    " from mart_rating_coverage order by language"
)


def test_rating_coverage_counts_films_ratings_likes_and_the_median_by_language(tmp_path):
    con = coverage_setup(tmp_path, 4.0)
    # en: 3 films, 2 rated, 3 + 1 = 4 ratings, likes (>= 4.0) 4.0, 4.5 and 4.0 = 3, median of
    # per-film counts (3, 1) = 2.0. te: 2 films, both rated, 2 + 1 = 3 ratings, likes 5.0 and
    # 4.0 = 2, median of (2, 1) = 1.5
    assert con.execute(COVERAGE_SQL).fetchall() == [
        ("en", 3, 2, 4, 3, 2.0),
        ("te", 2, 2, 3, 2, 1.5),
    ]


def test_rating_coverage_uses_the_like_rating_it_is_given(tmp_path):
    rows = coverage_setup(tmp_path, 3.5).execute(COVERAGE_SQL).fetchall()
    assert [r[4] for r in rows] == [4, 2]  # en: 3.5 counts now (4 likes); te unchanged


def test_like_counts_cut_at_validation_start_and_test_start_for_every_user(tmp_path):
    con = staged(tmp_path, [raw(10), raw(11), raw(12)])
    load_ratings(
        con,
        tmp_path,
        f"1,100,5.0,{epoch('2020-01-01')}\n"  # like, before validation
        f"2,100,3.5,{epoch('2021-10-12 00:00:00')}\n"  # like at 3.5, exactly val_start
        f"3,100,3.0,{epoch('2020-06-01')}\n"  # not a like at 3.5
        f"6,100,3.5,{epoch('2020-03-01')}\n"  # a like at 3.5 (not at 4.0), before validation
        f"4,100,4.0,{epoch('2022-10-12 00:00:00')}\n"  # exactly test_start
        f"5,100,4.0,{epoch('2022-10-11 23:59:59')}\n"  # last second before test_start
        f"9,110,4.0,{epoch('2023-10-12 08:00:00')}\n",  # sets the last rating day
        "100,0000010,10\n110,0000011,11\n120,0000012,12\n",
    )
    warehouse.build_staging(con, en_min_votes=1000)
    warehouse.write_clean(con, clean_frame(con))
    build_marts(con, like_rating=3.5)
    rows = con.execute(
        "select movie_id, likes_before_val, likes_before_test from mart_like_counts"
        " order by movie_id"
    ).fetchall()
    # film 10: before val_start users 1 and 6; before test_start users 1, 2, 5 and 6.
    # film 11 is rated (by user 9, after test_start) so it has a row of zeros; film 12 has none.
    assert rows == [(10, 2, 4), (11, 0, 0)]


def test_snapshot_reports_schema_count_and_sample(tmp_path):
    con = staged(tmp_path, [raw(2), raw(1)])
    snap = warehouse.snapshot(con, "stg_movies", n=1)
    assert snap["table"] == "stg_movies"
    assert snap["row_count"] == 2
    assert ["movie_id", "BIGINT"] in snap["columns"]
    assert len(snap["sample"]) == 1


def test_snapshot_rejects_unknown_table():
    con = warehouse.connect()
    with pytest.raises(ValueError, match="unknown table"):
        warehouse.snapshot(con, "stg_movies; drop table raw_movies")


def split_setup(tmp_path, ratings: str, **marts):
    con = staged(tmp_path, [raw(10), raw(11)])
    load_ratings(con, tmp_path, ratings, "100,0000010,10\n110,0000011,11\n")
    warehouse.build_staging(con, en_min_votes=1000)
    warehouse.write_clean(con, clean_frame(con))
    build_marts(con, **marts)
    return con


def epoch(text: str) -> int:
    return int(pd.Timestamp(text).timestamp())


def test_split_cutoffs_count_back_whole_months_from_the_last_rating_day(tmp_path):
    con = split_setup(
        tmp_path,
        f"1,100,4.0,{epoch('2023-10-12 10:30:00')}\n1,110,4.0,{epoch('2019-01-01')}\n",
        test_months=12,
        val_months=6,
    )
    row = con.execute("select last_rating, test_start, val_start from mart_split").fetchall()[0]
    assert [str(v) for v in row] == [
        "2023-10-12 10:30:00",
        "2022-10-12 00:00:00",
        "2022-04-12 00:00:00",
    ]


def test_model_ratings_keep_sampled_users_and_users_active_after_validation_start(tmp_path):
    late, old = epoch("2023-06-01"), epoch("2015-06-01")
    con = split_setup(
        tmp_path,
        f"4,100,4.0,{old}\n"  # user 4: 4 % 4 == 0, sampled for item-item learning
        f"5,100,4.0,{old}\n"  # user 5: old ratings only, not sampled -> not needed
        f"7,100,2.0,{old}\n7,110,5.0,{late}\n"  # user 7: active late -> all ratings kept
        f"9,110,3.0,{epoch('2023-10-12')}\n",  # sets the last rating day
        test_months=12,
        val_months=12,
        cf_user_mod=4,
    )
    rows = con.execute(
        "select user_id, movie_id, is_cf_user, is_eval_user from mart_model_ratings"
        " order by user_id, movie_id"
    ).fetchall()
    assert rows == [
        (4, 10, True, False),
        (7, 10, False, True),
        (7, 11, False, True),
        (9, 11, False, True),
    ]


def test_model_ratings_boundary_rating_exactly_at_validation_start_counts_as_late(tmp_path):
    con = split_setup(
        tmp_path,
        f"5,100,4.0,{epoch('2021-10-12 00:00:00')}\n"
        f"7,100,4.0,{epoch('2021-10-11 23:59:59')}\n"
        f"9,110,3.0,{epoch('2023-10-12 08:00:00')}\n",
        test_months=12,
        val_months=12,
        cf_user_mod=1000,
    )
    users = [
        r[0]
        for r in con.execute(
            "select distinct user_id from mart_model_ratings order by 1"
        ).fetchall()
    ]
    assert users == [5, 9]


def test_snapshot_sample_is_the_lowest_rows_not_insertion_order():
    con = warehouse.connect()
    con.execute("create table shuffled (x integer)").fetchall()
    con.execute("insert into shuffled values (3), (1), (2)").fetchall()
    assert warehouse.snapshot(con, "shuffled", n=2)["sample"] == [[1], [2]]


def test_a_file_warehouse_gets_a_memory_cap_a_spill_folder_and_unordered_inserts(tmp_path):
    con = warehouse.connect(tmp_path / "w.duckdb", memory_limit="1GB")
    memory, spill, ordered = con.execute(
        "select current_setting('memory_limit'), current_setting('temp_directory'),"
        " current_setting('preserve_insertion_order')"
    ).fetchall()[0]
    assert memory == "953.6 MiB"  # duckdb prints 1GB (10^9 bytes) in MiB
    assert spill == str(tmp_path / "w.tmp")
    assert ordered is False


def test_an_in_memory_warehouse_keeps_duckdb_defaults():
    con = warehouse.connect()
    assert con.execute("select current_setting('preserve_insertion_order')").fetchall() == [(True,)]
