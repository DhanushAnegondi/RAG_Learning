"""Missing data is filled, never dropped. Expected values are worked out by hand."""

import numpy as np
import pandas as pd
import pytest

from cinebridge import clean
from cinebridge.clean import CleanError

FILLED = [
    "title",
    "release_year",
    "runtime_min",
    "genres",
    "overview",
    "keywords",
    "directors",
    "cast_names",
    "imdb_rating",
    "imdb_votes",
]


def gappy(make_frame, make_movie) -> pd.DataFrame:
    """Twelve films, two languages, every fillable column missing somewhere."""
    rows = [make_movie(i, runtime_min=90 + i, release_year=1990 + i) for i in range(1, 7)]
    rows += [
        make_movie(i, language="te", runtime_min=150 + i, release_year=2010 + i, genres="Action")
        for i in range(7, 11)
    ]
    rows.append(
        make_movie(
            11,
            language="te",
            title=None,
            original_title="సీతా రామం",
            release_year=None,
            release_date=None,
            runtime_min=None,
            genres=None,
            overview=None,
            keywords=None,
            directors=None,
            cast_names=None,
            imdb_rating=None,
            imdb_votes=None,
        )
    )
    rows.append(make_movie(12, runtime_min=None, overview=None, keywords=None))
    return make_frame(*rows)


def test_no_row_is_dropped_and_order_is_kept(make_frame, make_movie):
    df = gappy(make_frame, make_movie)
    out = clean.clean_movies(df, min_df=1)
    assert out["movie_id"].tolist() == df["movie_id"].tolist()


def test_filled_columns_have_no_missing_values(make_frame, make_movie):
    out = clean.clean_movies(gappy(make_frame, make_movie), min_df=1)
    for col in FILLED:
        assert not out[col].isna().any(), col
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):
            assert (out[col].str.strip() != "").all(), col
    assert not out["score"].isna().any()


def test_observed_values_are_not_changed(make_frame, make_movie):
    df = gappy(make_frame, make_movie)
    out = clean.clean_movies(df, min_df=1)
    for col in FILLED:
        seen = df[col].notna().to_numpy()
        assert out.loc[seen, col].tolist() == df.loc[seen, col].tolist(), col


def test_flags_mark_exactly_the_filled_rows(make_frame, make_movie):
    df = gappy(make_frame, make_movie)
    out = clean.clean_movies(df, min_df=1)
    for col in FILLED:
        assert out[f"{col}_filled"].tolist() == df[col].isna().tolist(), col
        assert out[f"{col}_filled"].dtype == bool


def test_input_frame_is_not_mutated(make_frame, make_movie):
    df = gappy(make_frame, make_movie)
    before = df.copy(deep=True)
    clean.clean_movies(df, min_df=1)
    pd.testing.assert_frame_equal(df, before)


def test_title_falls_back_to_original_title_then_to_a_label(make_frame, make_movie):
    df = make_frame(
        make_movie(1, title=None, original_title="రౌద్రం"),
        make_movie(2, title=None, original_title=None),
    )
    out = clean.fill_title(df)
    assert out["title"].tolist() == ["రౌద్రం", "Untitled 2"]


def test_year_is_the_language_median_of_observed_years(make_frame, make_movie):
    df = make_frame(
        make_movie(1, release_year=1990),
        make_movie(2, release_year=2000),
        make_movie(3, release_year=2020),
        make_movie(4, release_year=None),
        make_movie(5, language="te", release_year=2015),
        make_movie(6, language="te", release_year=2019),
        make_movie(7, language="te", release_year=None),
    )
    out = clean.fill_year(df, min_df=1)
    assert out["release_year"].tolist() == [1990, 2000, 2020, 2000, 2015, 2019, 2017]
    assert str(out["release_year"].dtype) == "int64"


def test_year_comes_from_films_sharing_cast_before_the_language_median(make_frame, make_movie):
    """Found on the real run: 2024 releases were filled with the language median, 2012."""
    old = [
        make_movie(i, language="te", cast_names="N. T. Rama Rao", release_year=y)
        for i, y in enumerate([1962, 1965, 1970], 1)
    ]
    new = [make_movie(i, language="te", release_year=2015 + i) for i in range(4, 10)]
    gap = make_movie(10, language="te", cast_names="N. T. Rama Rao", release_year=None)
    lonely = make_movie(11, language="te", release_year=None)
    out = clean.fill_year(make_frame(*old, *new, gap, lonely), min_df=1)
    assert out["release_year"].iloc[-2] == 1965  # median of the three films sharing the actor
    assert out["release_year"].iloc[-1] == 2020  # nothing similar: Telugu median of 9 films
    assert out["release_year_filled"].tolist() == [False] * 9 + [True, True]


def test_a_filled_number_is_rounded_not_truncated(make_frame, make_movie):
    df = make_frame(
        make_movie(1, language="te", release_year=2016),
        make_movie(2, language="te", release_year=2019),
        make_movie(3, language="te", release_year=None),
    )
    # median 2017.5 rounds to 2018 (half to even); truncating would give 2017
    assert clean.fill_year(df, min_df=1)["release_year"].iloc[2] == 2018


def test_year_with_no_observed_value_in_the_language_uses_all_films(make_frame, make_movie):
    df = make_frame(
        make_movie(1, release_year=1990),
        make_movie(2, release_year=2010),
        make_movie(3, language="te", release_year=None),
    )
    assert clean.fill_year(df, min_df=1)["release_year"].tolist() == [1990, 2010, 2000]


def test_year_with_nothing_observed_raises(make_frame, make_movie):
    df = make_frame(make_movie(1, release_year=None))
    with pytest.raises(CleanError, match="release_year"):
        clean.fill_year(df, min_df=1)


def test_runtime_uses_language_and_first_genre_when_the_group_is_big_enough(make_frame, make_movie):
    rows = [
        make_movie(i, genres="Action, Drama", runtime_min=r)
        for i, r in enumerate([100, 110, 120], 1)
    ]
    rows += [make_movie(i, genres="Comedy", runtime_min=r) for i, r in enumerate([80, 84], 4)]
    rows += [
        make_movie(6, genres="Action", runtime_min=None),  # group Action has 3 observed
        make_movie(7, genres="Comedy", runtime_min=None),  # group Comedy has 2: too small
        make_movie(8, language="te", genres="Action", runtime_min=None),  # no Telugu values
    ]
    out = clean.fill_runtime(make_frame(*rows), min_group=3)
    assert out["runtime_min"].tolist()[5:] == [110, 100, 100]
    assert out["runtime_min_filled"].tolist() == [False] * 5 + [True] * 3


def test_runtime_medians_ignore_other_languages(make_frame, make_movie):
    rows = [make_movie(i, runtime_min=90) for i in range(1, 4)]
    rows += [make_movie(i, language="te", runtime_min=160) for i in range(4, 7)]
    rows.append(make_movie(7, language="te", runtime_min=None))
    out = clean.fill_runtime(make_frame(*rows), min_group=3)
    assert out["runtime_min"].iloc[-1] == 160


def test_genres_come_from_the_most_similar_films(make_frame, make_movie):
    rows = [
        make_movie(1, directors="Rajamouli", genres="Action, Fantasy"),
        make_movie(2, directors="Rajamouli", genres="Action, Drama"),
        make_movie(3, directors="Rajamouli", genres="Action"),
        make_movie(4, directors="Someone Else", genres="Comedy"),
        make_movie(5, directors="Rajamouli", genres=None),
    ]
    out = clean.fill_genres(make_frame(*rows), k=3, min_df=1)
    assert out["genres"].iloc[4] == "Action"
    assert out["genres_fill_method"].tolist() == ["observed"] * 4 + ["neighbours"]


def test_genres_keep_every_genre_with_at_least_half_the_top_vote(make_frame, make_movie):
    rows = [
        make_movie(1, directors="D", genres="Action, Thriller"),
        make_movie(2, directors="D", genres="Action, Thriller"),
        make_movie(3, directors="D", genres="Action, Romance"),
        make_movie(4, directors="D", genres=None),
    ]
    out = clean.fill_genres(make_frame(*rows), k=3, min_df=1)
    # votes: Action 3, Thriller 2, Romance 1 (equal similarities); half of top = 1.5
    assert out["genres"].iloc[3] == "Action, Thriller"


def test_genres_fall_back_to_the_language_favourite_when_nothing_is_similar(make_frame, make_movie):
    rows = [
        make_movie(1, genres="Drama"),
        make_movie(2, genres="Drama"),
        make_movie(3, genres="Comedy"),
        make_movie(4, language="te", genres="Action"),
        make_movie(5, language="te", genres="Action, Drama"),
        make_movie(
            6,
            language="te",
            genres=None,
            overview=None,
            keywords=None,
            directors=None,
            cast_names=None,
        ),
    ]
    out = clean.fill_genres(make_frame(*rows), k=3, min_df=1)
    assert out["genres"].iloc[5] == "Action"
    assert out["genres_fill_method"].iloc[5] == "language_mode"


def test_overview_is_built_from_the_film_s_own_fields(make_frame, make_movie):
    df = make_frame(
        make_movie(
            1,
            overview=None,
            genres="Action, Drama",
            directors="Sukumar",
            cast_names="Allu Arjun, Rashmika Mandanna, Fahadh Faasil, Sunil",
            tagline="The rise.",
        ),
        make_movie(2, overview=None, genres="Comedy", directors=None, cast_names=None),
    )
    out = clean.fill_overview(clean.fill_people(df))
    assert out["overview"].iloc[0] == (
        "Action, Drama film directed by Sukumar, starring Allu Arjun, Rashmika Mandanna,"
        " Fahadh Faasil. The rise."
    )
    assert out["overview"].iloc[1] == "Comedy film."
    assert "Unknown" not in out["overview"].iloc[1]


def test_keywords_are_drawn_from_the_film_s_own_overview(make_frame, make_movie):
    df = make_frame(
        make_movie(1, overview="a heist on a moving train", keywords=None),
        make_movie(2, overview="a quiet village wedding", keywords="wedding"),
        make_movie(3, overview="a village festival", keywords="festival"),
    )
    df["overview_filled"] = False
    out = clean.fill_keywords(df, top_n=5, min_df=1)
    words = out["keywords"].iloc[0].split(", ")
    assert set(words) <= {"heist", "moving", "train"}
    assert "heist" in words and "train" in words
    assert out["keywords"].tolist()[1:] == ["wedding", "festival"]


def test_keywords_for_a_filled_overview_come_from_genres(make_frame, make_movie):
    df = make_frame(
        make_movie(1, overview="Action, Drama film.", keywords=None, genres="Action, Drama")
    )
    df["overview_filled"] = True
    out = clean.fill_keywords(df, top_n=5, min_df=1)
    assert out["keywords"].iloc[0] == "action, drama"


def test_people_get_a_placeholder_and_a_flag(make_frame, make_movie):
    df = make_frame(make_movie(1, directors=None, cast_names=None), make_movie(2))
    out = clean.fill_people(df)
    assert out["directors"].tolist() == ["Unknown", "Director 2"]
    assert out["cast_names"].tolist() == ["Unknown", "Actor 2"]
    assert out["directors_filled"].tolist() == [True, False]
    assert out["cast_names_filled"].tolist() == [True, False]


def test_score_shrinks_low_vote_films_toward_the_language_mean(make_frame, make_movie):
    df = make_frame(
        make_movie(1, imdb_rating=9.0, imdb_votes=100),
        make_movie(2, imdb_rating=5.0, imdb_votes=300),
        make_movie(3, imdb_rating=7.0, imdb_votes=200),
        make_movie(4, imdb_rating=None, imdb_votes=None),
    )
    out = clean.fill_rating(df)
    # observed mean C = 7.0, median votes m = 200
    assert out["imdb_rating"].tolist() == [9.0, 5.0, 7.0, 7.0]
    assert out["imdb_votes"].tolist() == [100, 300, 200, 0]
    expected = [(100 * 9 + 200 * 7) / 300, (300 * 5 + 200 * 7) / 500, 7.0, 7.0]
    assert out["score"].tolist() == pytest.approx(expected)
    assert out["imdb_rating_filled"].tolist() == [False, False, False, True]
    assert out["imdb_votes_filled"].tolist() == [False, False, False, True]


def test_score_uses_each_language_s_own_mean(make_frame, make_movie):
    df = make_frame(
        make_movie(1, imdb_rating=8.0, imdb_votes=10),
        make_movie(2, language="te", imdb_rating=6.0, imdb_votes=10),
        make_movie(3, language="te", imdb_rating=None, imdb_votes=None),
    )
    assert clean.fill_rating(df)["score"].iloc[2] == pytest.approx(6.0)


class FirstRows:
    """Stands in for numpy's generator: hide the first rows of each language pool, so the
    hidden rows (and every expected error below) can be worked out by hand."""

    def choice(self, pool, size, replace):
        return pool[:size]


@pytest.fixture
def first_rows(monkeypatch):
    monkeypatch.setattr(clean.np.random, "default_rng", lambda seed: FirstRows())


def masked_world(make_frame, make_movie) -> pd.DataFrame:
    """40 films. With frac=0.25 the first 5 films of each language are hidden (ids 1-5, 21-25).

    en 1-5:   Drama, Family,    cast OLD,  runtime 100, year 1990
    en 6-10:  Drama,            cast OLD,  runtime 100, year 1990
    en 11-20: Comedy, Romance, Family, runtime 120, year 2010
    te 21-30: Action,           cast OLD2, runtime 150, year 1980
    te 31-40: Drama, Thriller, Crime, runtime 170, year 2015
    """
    rows = [
        make_movie(
            i,
            genres="Drama, Family" if i <= 5 else "Drama",
            cast_names="OLD",
            runtime_min=100,
            release_year=1990,
        )
        for i in range(1, 11)
    ]
    rows += [
        make_movie(i, genres="Comedy, Romance, Family", runtime_min=120, release_year=2010)
        for i in range(11, 21)
    ]
    rows += [
        make_movie(
            i,
            language="te",
            genres="Action",
            cast_names="OLD2",
            runtime_min=150,
            release_year=1980,
        )
        for i in range(21, 31)
    ]
    rows += [
        make_movie(
            i,
            language="te",
            genres="Drama, Thriller, Crime",
            runtime_min=170,
            release_year=2015,
        )
        for i in range(31, 41)
    ]
    return make_frame(*rows)


def test_masked_check_scores_fills_and_a_fair_naive_fill(first_rows, make_frame, make_movie):
    df = masked_world(make_frame, make_movie)
    before = df.copy(deep=True)
    report = clean.masked_fill_check(df, frac=0.25, seed=7, min_df=1, min_group=5)
    pd.testing.assert_frame_equal(df, before)
    got = report.set_index(["column_name", "language"])
    assert list(report["column_name"].unique()) == ["runtime_min", "release_year", "genres"]
    assert list(report["language"].unique()) == ["all", "en", "te"]
    assert report["masked_rows"].tolist() == [10, 5, 5] * 3
    # runtime: hidden en 1-5 (truth 100) are refilled from the (en, Drama) group: 5 observed
    # left, median 100, exact. Naive = en median of what is left: 5 x 100 + 10 x 120 -> 120,
    # off by 20. Same for te: group (te, Action) gives 150; naive median 170, off by 20.
    # (one median over both languages would be 135: off by 35 and 15, not 20)
    for lang in ("all", "en", "te"):
        assert got.loc[("runtime_min", lang), "fill_error"] == pytest.approx(0.0)
        assert got.loc[("runtime_min", lang), "naive_error"] == pytest.approx(20.0)
    # year: hidden films share their cast with the films kept (cast OLD / OLD2), so the median
    # year of those neighbours is exact. Naive en: 5 x 1990 + 10 x 2010 -> 2010, off by 20;
    # te: 5 x 1980 + 10 x 2015 -> 2015, off by 35; all = (5 * 20 + 5 * 35) / 10
    for lang in ("all", "en", "te"):
        assert got.loc[("release_year", lang), "fill_error"] == pytest.approx(0.0)
    assert got.loc[("release_year", "en"), "naive_error"] == pytest.approx(20.0)
    assert got.loc[("release_year", "te"), "naive_error"] == pytest.approx(35.0)
    assert got.loc[("release_year", "all"), "naive_error"] == pytest.approx(27.5)
    # genres: hidden films take the genre of their cast-mates (exact: Drama is one of "Drama,
    # Family", Action is "Action"). Naive = the language's 3 commonest genres among films left:
    # en Comedy, Family, Romance (10 each; Drama has 5): the truth "Drama, Family" holds Family,
    # a hit, so 0.0 (a one-genre guess, Comedy, would miss); te Crime, Drama, Thriller (10 each;
    # Action has 5): the truth "Action" is not among them, so 1.0. all = (5 * 0 + 5 * 1) / 10.
    for lang in ("all", "en", "te"):
        assert got.loc[("genres", lang), "fill_error"] == pytest.approx(0.0)
    assert got.loc[("genres", "en"), "naive_error"] == pytest.approx(0.0)
    assert got.loc[("genres", "te"), "naive_error"] == pytest.approx(1.0)
    assert got.loc[("genres", "all"), "naive_error"] == pytest.approx(0.5)
    assert got.loc[("runtime_min", "all"), "metric"] == "mean abs error, minutes"
    assert got.loc[("release_year", "all"), "metric"] == "mean abs error, years"
    assert got.loc[("genres", "all"), "metric"] == "share with no correct genre"


def test_masked_check_fills_see_observed_values_only(first_rows, make_frame, make_movie):
    """Films 3-4 carry a runtime the pipeline filled (flag set, value extreme). The check must
    treat them as missing, as the pipeline's own fill does, and never score them."""
    rows = [make_movie(i, genres="Drama", runtime_min=100) for i in (1, 2)]
    rows += [make_movie(i, genres="Drama", runtime_min=999) for i in (3, 4)]
    rows += [make_movie(i, genres="Comedy", runtime_min=120) for i in (5, 6, 7, 8)]
    rows += [
        make_movie(i, language="te", genres="Action", runtime_min=160) for i in (9, 10, 11, 12)
    ]
    df = make_frame(*rows)
    df["runtime_min_filled"] = [False, False, True, True] + [False] * 8
    report = clean.masked_fill_check(df, frac=0.5, seed=7, min_df=1, min_group=2)
    en = report[(report["column_name"] == "runtime_min") & (report["language"] == "en")].iloc[0]
    # en pool = films 1, 2, 5, 6, 7, 8 (not the filled 3, 4); hidden = 1, 2, 5 (truths 100,
    # 100, 120).
    # Films 3, 4 become missing, so group (en, Drama) is empty -> language median of films
    # 6, 7, 8 = 120: errors 20, 20; film 5 from group (en, Comedy) = 120: error 0.
    assert en["masked_rows"] == 3
    assert en["fill_error"] == pytest.approx(40 / 3)
    # naive: en median of films left (6, 7, 8) = 120 -> the same three errors
    assert en["naive_error"] == pytest.approx(40 / 3)


def test_masked_check_is_repeatable_for_a_seed_and_follows_it(make_frame, make_movie):
    rng = np.random.default_rng(0)
    rows = [
        make_movie(
            i, runtime_min=int(rng.integers(80, 180)), release_year=int(rng.integers(1980, 2024))
        )
        for i in range(1, 41)
    ]
    df = make_frame(*rows)
    a = clean.masked_fill_check(df, frac=0.2, seed=3, min_df=1)
    b = clean.masked_fill_check(df, frac=0.2, seed=3, min_df=1)
    other = clean.masked_fill_check(df, frac=0.2, seed=4, min_df=1)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(other)  # another seed hides other films


def test_clean_refuses_to_return_fewer_rows(make_frame, make_movie, monkeypatch):
    real = clean.fill_runtime
    monkeypatch.setattr(clean, "fill_runtime", lambda df, **kw: real(df, **kw).iloc[1:])
    with pytest.raises(CleanError, match="rows changed"):
        clean.clean_movies(gappy(make_frame, make_movie), min_df=1)


def test_clean_refuses_to_return_a_gap(make_frame, make_movie, monkeypatch):
    def leaves_a_gap(df, **kw):
        out = df.copy()
        out["runtime_min_filled"] = out["runtime_min"].isna()
        return out

    monkeypatch.setattr(clean, "fill_runtime", leaves_a_gap)
    with pytest.raises(CleanError, match="runtime_min: 2 values still missing"):
        clean.clean_movies(gappy(make_frame, make_movie), min_df=1)


def test_genre_votes_are_weighted_by_similarity(make_frame, make_movie):
    # films 2, 3, 4 are the only neighbours of film 1 (text only; genres are not compared).
    # text similarity to film 1 (x 1/1.36 for the people block): film 2 shares all four words
    # -> 0.735; films 3 and 4 share one word each -> 0.176. Votes: Thriller 0.735 against
    # Comedy 0.176 + 0.176 = 0.352 < half of 0.735, so Comedy is dropped. By head count
    # (2 against 1) Comedy would lead and Thriller would be kept too.
    rows = [
        make_movie(1, overview="river heist vault gold", genres=None, keywords=None),
        make_movie(2, overview="river heist vault gold", genres="Thriller", keywords=None),
        make_movie(3, overview="gold coins", genres="Comedy", keywords=None),
        make_movie(4, overview="vault door", genres="Comedy", keywords=None),
    ]
    out = clean.fill_genres(make_frame(*rows), k=3, min_df=1)
    assert out["genres"].iloc[0] == "Thriller"


def test_only_the_k_nearest_films_vote_for_genres(make_frame, make_movie):
    same = "river heist vault gold"
    rows = [
        make_movie(1, overview=same, genres=None, keywords=None),
        make_movie(2, overview=same, genres="Thriller", keywords=None),
        make_movie(3, overview=same, genres="Comedy", keywords=None),
        make_movie(4, overview=same, genres="Comedy", keywords=None),
    ]
    # three equally similar films; ties go to the lower index
    assert clean.fill_genres(make_frame(*rows), k=1, min_df=1)["genres"].iloc[0] == "Thriller"
    # all three vote: Comedy 2 shares, Thriller 1 (>= half of 2): both kept, strongest first
    assert clean.fill_genres(make_frame(*rows), k=3, min_df=1)["genres"].iloc[0] == (
        "Comedy, Thriller"
    )


def test_a_film_gets_at_most_three_genres_and_ties_go_alphabetically(make_frame, make_movie):
    rows = [
        make_movie(1, directors="D", genres="Drama, Action, Comedy, Biopic"),
        make_movie(2, directors="D", genres=None),
    ]
    out = clean.fill_genres(make_frame(*rows), k=3, min_df=1)
    assert out["genres"].iloc[1] == "Action, Biopic, Comedy"  # four tie on one vote


def test_year_uses_only_the_k_nearest_films(make_frame, make_movie):
    rows = [
        make_movie(i, language="te", cast_names="X", release_year=y)
        for i, y in ((1, 1960), (2, 1970), (3, 2000))
    ]
    rows.append(make_movie(4, language="te", cast_names="X", release_year=None))
    out = clean.fill_year(make_frame(*rows), k=2, min_df=1)
    assert out["release_year"].iloc[3] == 1965  # median of 1960 and 1970, not of all three


def test_runtime_thin_group_falls_back_to_the_language_median_not_the_global_one(
    make_frame, make_movie
):
    rows = [make_movie(i, genres="Action", runtime_min=100) for i in (1, 2, 3)]
    rows += [
        make_movie(4, language="te", genres="Action", runtime_min=160),
        make_movie(5, language="te", genres="Action", runtime_min=170),
        make_movie(6, language="te", genres="Comedy", runtime_min=None),
    ]
    out = clean.fill_runtime(make_frame(*rows), min_group=3)
    assert out["runtime_min"].iloc[-1] == 165  # Telugu median of 160, 170; global would be 100


def test_score_weight_is_the_median_votes_of_the_film_s_own_language(make_frame, make_movie):
    rows = [make_movie(i, imdb_rating=6.0, imdb_votes=v) for i, v in ((1, 10), (2, 20), (3, 30))]
    rows += [
        make_movie(4, language="te", imdb_rating=8.0, imdb_votes=1000),
        make_movie(5, language="te", imdb_rating=6.0, imdb_votes=2000),
        make_movie(6, language="te", imdb_rating=4.0, imdb_votes=3000),
    ]
    out = clean.fill_rating(make_frame(*rows))
    # Telugu: C = mean(8, 6, 4) = 6, m = median votes 2000 -> film 4: (1000 * 8 + 2000 * 6) / 3000
    assert out["score"].iloc[3] == pytest.approx((1000 * 8 + 2000 * 6) / 3000)


def test_language_favourite_tie_goes_to_the_alphabetically_first_genre(make_frame, make_movie):
    blank = {"overview": None, "keywords": None, "directors": None, "cast_names": None}
    rows = [
        make_movie(1, language="te", genres="Drama"),
        make_movie(2, language="te", genres="Action"),
        make_movie(3, language="te", genres=None, **blank),
    ]
    out = clean.fill_genres(make_frame(*rows), k=3, min_df=1)
    assert out["genres"].iloc[2] == "Action"
    assert out["genres_fill_method"].iloc[2] == "language_mode"


def test_keywords_keep_only_the_top_n_words(make_frame, make_movie):
    df = make_frame(make_movie(1, overview="alpha bravo charlie delta echo foxtrot", keywords=None))
    df["overview_filled"] = False
    out = clean.fill_keywords(df, top_n=5, min_df=1)
    # one document: every word weighs the same, so the first five alphabetically win
    assert out["keywords"].iloc[0] == "alpha, bravo, charlie, delta, echo"


def test_keywords_fall_back_to_genres_when_the_overview_has_no_usable_words(make_frame, make_movie):
    df = make_frame(make_movie(1, overview="the of and", keywords=None, genres="Action, Drama"))
    out = clean.fill_keywords(df, min_df=1)
    assert out["keywords"].iloc[0] == "action, drama"


def test_fills_refuse_when_nothing_is_observed_to_fill_from(make_frame, make_movie):
    with pytest.raises(CleanError, match="genres"):
        clean.fill_genres(make_frame(make_movie(1, genres=None)), min_df=1)
    with pytest.raises(CleanError, match="runtime_min"):
        clean.fill_runtime(make_frame(make_movie(1, runtime_min=None)))
    with pytest.raises(CleanError, match="imdb_rating"):
        clean.fill_rating(make_frame(make_movie(1, imdb_rating=None)))


def test_overview_needs_genres_to_be_filled_first(make_frame, make_movie):
    with pytest.raises(CleanError, match="fill genres before overview"):
        clean.fill_overview(make_frame(make_movie(1, overview=None, genres=None)))


def test_keywords_need_genres_when_there_is_no_overview_to_mine(make_frame, make_movie):
    df = make_frame(make_movie(1, overview=None, keywords=None, genres=None))
    df["overview_filled"] = True
    with pytest.raises(CleanError, match="fill genres before keywords"):
        clean.fill_keywords(df, min_df=1)
