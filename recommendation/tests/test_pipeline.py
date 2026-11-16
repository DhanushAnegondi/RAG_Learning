"""Pipeline helpers: what the models may learn from, and what the page says."""

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from cinebridge import clean, pipeline
from cinebridge.config import Settings
from cinebridge.features import build_item_matrix


def model_ratings(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["user_id", "movie_id", "rating", "rated_at", "is_cf_user"])
    df["rated_at"] = pd.to_datetime(df["rated_at"])
    df["is_eval_user"] = True
    return df


def csr(rows: list[list[float]]) -> sparse.csr_matrix:
    return sparse.csr_matrix(np.array(rows, dtype=np.float32))


# ---- collaborative fit, popularity, parts ------------------------------------------------------


def test_collaborative_fit_uses_only_sampled_users_likes_before_the_cutoff():
    ratings = model_ratings(
        [
            (1, 10, 5.0, "2020-01-01", True),
            (1, 11, 4.0, "2020-01-02", True),
            (2, 10, 4.5, "2020-01-03", True),
            (2, 11, 2.0, "2020-01-04", True),  # not a like
            (3, 10, 5.0, "2020-01-05", False),  # not a sampled user: would make 10 and 11
            (3, 11, 5.0, "2020-01-05", False),  # look more popular (2 / sqrt(3 * 2))
            (1, 12, 5.0, "2021-01-01", True),  # exactly at the cutoff: the future
            (2, 12, 5.0, "2021-06-01", True),  # after the cutoff
        ]
    )
    settings = Settings(cf_shrink=0.0, cf_neighbors=2)
    neighbors = pipeline.fit_collaborative(
        ratings, pd.Timestamp("2021-01-01"), [10, 11, 12], settings
    )
    dense = neighbors.toarray()
    # likes before the cutoff by sampled users: u1 liked 10 and 11, u2 liked 10 only
    assert dense[0, 1] == pytest.approx(1 / np.sqrt(2 * 1))
    assert dense[2].tolist() == [0.0, 0.0, 0.0]
    assert dense[:, 2].tolist() == [0.0, 0.0, 0.0]


def test_collaborative_fit_counts_a_repeated_like_once():
    ratings = model_ratings(
        [
            (1, 10, 5.0, "2020-01-01", True),
            (1, 10, 4.0, "2020-01-02", True),  # the same user and film again
            (1, 11, 4.0, "2020-01-03", True),
            (2, 10, 4.0, "2020-01-04", True),
            (2, 11, 4.0, "2020-01-05", True),
        ]
    )
    settings = Settings(cf_shrink=0.0, cf_neighbors=2)
    neighbors = pipeline.fit_collaborative(ratings, pd.Timestamp("2021-01-01"), [10, 11], settings)
    # films 10 and 11 are each liked by both users: 2 / sqrt(2 * 2) = 1.0 (a double count of
    # user 1's like of film 10 would give 3 / sqrt(3 * 2))
    assert neighbors.toarray()[0, 1] == pytest.approx(1.0)


def test_popularity_vector_is_aligned_to_the_film_order_and_reads_the_asked_column():
    counts = pd.DataFrame(
        {"movie_id": [30, 10], "likes_before_val": [7, 3], "likes_before_test": [9, 4]}
    )
    got = pipeline.popularity_vector(counts, [10, 20, 30], "likes_before_val")
    assert got.tolist() == [3.0, 0.0, 7.0]  # film 20 has no likes at all
    assert got.dtype == np.float32
    assert pipeline.popularity_vector(counts, [10, 20, 30], "likes_before_test").tolist() == [
        4.0,
        0.0,
        9.0,
    ]


def test_parts_score_in_film_order():
    items = csr([[1, 0], [1, 0], [0, 1]])
    neighbors = csr([[0, 0, 1], [0, 0, 0], [1, 0, 0]])
    popularity = np.array([5, 1, 3], dtype=np.float32)
    profile = csr([[1, 0, 0]])
    parts = pipeline.score_parts(items, neighbors, popularity)
    assert list(parts) == ["popularity", "content", "item_item"]
    assert parts["popularity"](profile).tolist() == [[5.0, 1.0, 3.0]]
    assert parts["content"](profile)[0] == pytest.approx([1.0, 1.0, 0.0])
    assert parts["item_item"](profile)[0] == pytest.approx([0.0, 0.0, 1.0])


def test_weight_grid_covers_the_simplex_content_first():
    grid = pipeline.weight_grid(0.5)
    # content-heavy first; within a content level, more item-item first
    assert [(w["content"], w["item_item"], w["popularity"]) for w in grid] == [
        (1.0, 0.0, 0.0),
        (0.5, 0.5, 0.0),
        (0.5, 0.0, 0.5),
        (0.0, 1.0, 0.0),
        (0.0, 0.5, 0.5),
        (0.0, 0.0, 1.0),
    ]


def test_weight_grid_of_a_quarter_has_fifteen_blends_that_each_sum_to_one():
    grid = pipeline.weight_grid(0.25)
    assert len(grid) == 15
    assert all(abs(sum(w.values()) - 1.0) < 1e-9 for w in grid)


# ---- release dates and the evaluation windows --------------------------------------------------


def test_released_before_keeps_unknown_dates_and_films_released_inside_the_window():
    dates = pd.Series(
        pd.to_datetime(["2000-01-01", "2022-10-11", "2022-10-12", None, "2023-03-01"])
    )
    got = pipeline.released_before(dates, pd.Timestamp("2022-10-12"))
    # released on or after the window end cannot have been rated inside it
    assert got.tolist() == [True, True, False, True, False]


ITEM_IDS = [10, 11, 12, 13, 14, 15, 16, 17]
RELEASED = pd.Series(
    pd.to_datetime(
        [
            "2000-01-01",  # 10
            "2000-01-01",  # 11
            "2000-01-01",  # 12
            "2023-03-01",  # 13 released inside the test window
            "2024-01-01",  # 14 released after everything
            None,  # 15 unknown date
            "2022-10-12",  # 16 released exactly on test_start (the validation window end)
            "2023-10-13",  # 17 released exactly on the test window end
        ]
    )
)
VAL_START, TEST_START, WINDOW_END = (
    pd.Timestamp("2021-10-12"),
    pd.Timestamp("2022-10-12"),
    pd.Timestamp("2023-10-13"),
)
LIKE_COUNTS = pd.DataFrame(
    {
        "movie_id": [10, 12, 15],
        "likes_before_val": [3, 1, 2],
        "likes_before_test": [5, 4, 6],
    }
)


def leak_ratings() -> pd.DataFrame:
    """Users 1 and 3 liked a film in each window; user 2 only in the test window.

    films: 10, 15 liked before validation; 11 liked inside validation; 12 liked inside test.
    """
    return model_ratings(
        [
            (1, 10, 5.0, "2020-06-01", True),
            (1, 11, 4.0, "2021-12-01", True),  # validation window
            (1, 12, 4.0, "2023-01-01", True),  # test window
            (2, 10, 5.0, "2020-06-01", True),
            (2, 12, 4.0, "2023-01-01", True),  # test window only
            (3, 10, 5.0, "2020-01-01", True),
            (3, 15, 4.0, "2020-02-01", True),
            (3, 11, 4.0, "2022-01-01", True),  # validation window
            (3, 12, 4.0, "2023-02-01", True),  # test window
        ]
    )


def windows():
    return pipeline.eval_windows(
        leak_ratings(),
        VAL_START,
        TEST_START,
        WINDOW_END,
        ITEM_IDS,
        RELEASED,
        LIKE_COUNTS,
        Settings(min_profile_likes=1, cf_shrink=0.0, cf_neighbors=5),
    )


def test_validation_window_never_sees_a_test_window_rating():
    v = windows()["validation"]
    assert v["users"].tolist() == [1, 3]  # user 2 liked nothing inside validation
    # items in ITEM_IDS order: 10 11 12 13 14 15 16 17
    assert v["profile"].toarray().tolist() == [[1, 0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 1, 0, 0]]
    assert v["seen"].toarray().tolist() == [[1, 0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 1, 0, 0]]
    assert v["relevant"].toarray().tolist() == [[0, 1, 0, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0, 0, 0]]
    neighbors = v["neighbors"].toarray()
    assert neighbors[0, 5] > 0  # 10 and 15 were both liked by user 3 before validation
    assert neighbors[0, 1] == 0.0  # 10 and 11: user 3 liked 11 only inside validation
    assert neighbors[0, 2] == 0.0  # 10 and 12: only in the test window


def test_test_window_profile_and_seen_include_the_validation_window_but_not_test_ratings():
    t = windows()["test"]
    assert t["users"].tolist() == [1, 2, 3]
    assert t["profile"].toarray().tolist() == [
        [1, 1, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 1, 0, 0],
    ]
    assert t["seen"].toarray().tolist() == t["profile"].toarray().tolist()
    assert t["relevant"].toarray().tolist() == [
        [0, 0, 1, 0, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0, 0, 0],
    ]
    neighbors = t["neighbors"].toarray()
    assert neighbors[0, 1] > 0  # user 3's validation-window like of 11 is past by the test cutoff
    assert neighbors[0, 2] == 0.0  # nobody's test-window like is used


def test_popularity_comes_from_the_like_count_column_of_each_window():
    w = windows()
    # films 10, 12, 15 sit at positions 0, 2, 5
    assert w["validation"]["popularity"].tolist() == [3, 0, 1, 0, 0, 2, 0, 0]
    assert w["test"]["popularity"].tolist() == [5, 0, 4, 0, 0, 6, 0, 0]


def test_candidates_drop_films_released_on_or_after_each_window_end():
    w = windows()
    # validation window ends at test_start 2022-10-12: out are 13 (2023-03), 14, 16 (that very
    # day) and 17
    assert w["validation"]["candidates"].tolist() == [
        True,
        True,
        True,
        False,
        False,
        True,
        False,
        False,
    ]
    assert w["validation"]["excluded"] == 4
    # test window ends 2023-10-13: out are 14 and 17 (that very day); 13 and 16 stay
    assert w["test"]["candidates"].tolist() == [True, True, True, True, False, True, True, False]
    assert w["test"]["excluded"] == 2


def toy_window(relevant, popularity=(0, 0, 1, 5)):
    """4 films: items 0-1 point one way, 2-3 the other. Three users who liked film 0."""
    return {
        "users": np.array([1, 2, 3]),
        "profile": csr([[1, 0, 0, 0]] * 3),
        "seen": csr([[1, 0, 0, 0]] * 3),
        "relevant": csr(relevant),
        "candidates": np.ones(4, dtype=bool),
        "excluded": 0,
        "neighbors": sparse.csr_matrix((4, 4), dtype=np.float32),
        "popularity": np.array(popularity, dtype=np.float32),
    }


TOY_ITEMS = csr([[1, 0], [1, 0], [0, 1], [0, 1]])
TOY_TELUGU = np.array([False, True, True, False])
POP_ONLY = {"content": 0.0, "item_item": 0.0, "popularity": 1.0}
CONTENT_ONLY = {"content": 1.0, "item_item": 0.0, "popularity": 0.0}


def toy_windows():
    # validation: two users want film 3 (popularity finds it), one wants film 1 (content does);
    # test: everyone wants film 1, which would make content the winner if it were looked at
    return {
        "validation": toy_window([[0, 0, 0, 1], [0, 0, 0, 1], [0, 1, 0, 0]]),
        "test": toy_window([[0, 1, 0, 0]] * 3),
    }


def test_blend_weights_are_chosen_on_validation_data_only():
    settings = Settings(k=1, weight_step=1.0, min_validation_users=1)
    weights, table, fallback = pipeline.choose_shelf_weights(
        toy_windows(), TOY_ITEMS, TOY_TELUGU, settings
    )
    # all films: popularity hits users 1 and 2 (2 of 3), content only user 3 (1 of 3)
    assert weights["all films"] == POP_ONLY
    # Telugu shelf (films 1, 2): only user 3 wants a shelf film; content finds it, popularity
    # would pick film 2
    assert weights["Telugu shelf"] == CONTENT_ONLY
    assert fallback is False
    assert table.groupby("shelf")["users"].first().to_dict() == {"Telugu shelf": 1, "all films": 3}
    assert len(table) == 6  # three blends for each shelf


def test_weights_ignore_films_that_cannot_be_hits_in_the_validation_window():
    """Film 3 (the most popular) was released after the window: it is not a candidate, so popularity
    must be judged on its best film that could be hit, film 2."""
    v = toy_window([[0, 0, 1, 0]] * 3, popularity=(0, 0, 5, 9))
    v["candidates"] = np.array([True, True, True, False])
    settings = Settings(k=1, weight_step=1.0, min_validation_users=1)
    weights, _, _ = pipeline.choose_shelf_weights(
        {"validation": v, "test": v}, TOY_ITEMS, np.array([False, False, True, True]), settings
    )
    assert weights["all films"] == POP_ONLY  # without the mask popularity misses and content wins
    assert weights["Telugu shelf"] == POP_ONLY


def test_a_shelf_with_too_few_validation_users_uses_the_all_films_weights():
    settings = Settings(k=1, weight_step=1.0, min_validation_users=2)
    weights, _, fallback = pipeline.choose_shelf_weights(
        toy_windows(), TOY_ITEMS, TOY_TELUGU, settings
    )
    assert fallback is True
    assert weights["Telugu shelf"] == POP_ONLY  # 1 validation user < 2: fall back
    assert weights["all films"] == POP_ONLY


def test_test_scoring_uses_the_test_candidates_and_each_shelf_s_own_weights():
    test = toy_window([[0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1]], popularity=(0, 9, 1, 5))
    test["candidates"] = np.array([True, False, True, True])  # film 1 (pop 9) cannot be a hit
    # user 2 has a Telugu film (2) in their history; users 1 and 3 do not
    test["profile"] = test["seen"] = csr([[1, 0, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]])
    result = pipeline.score_test(
        {"validation": toy_window([[0, 0, 0, 1]] * 3), "test": test},
        TOY_ITEMS,
        {"all films": POP_ONLY, "Telugu shelf": CONTENT_ONLY},
        np.array([False, True, True, True]),  # film 1 is Telugu too, but cannot be a hit
        k=1,
    ).set_index(["slice", "method"])
    assert list(result.index.get_level_values("slice").unique()) == [
        "all",
        "telugu",
        "telugu_first_time",
    ]
    # popularity (film 1 not allowed): everyone's best unseen film is 3 -> hits for all three
    assert result.loc[("all", "popularity"), ["users", "recall_at_k"]].tolist() == [3, 1.0]
    assert result.loc[("all", "hybrid"), "recall_at_k"] == 1.0  # all-films weights: popularity
    assert result.loc[("telugu", "popularity"), ["users", "recall_at_k"]].tolist() == [3, 1.0]
    # the Telugu hybrid uses the Telugu-shelf weights (content only). Content scores are zero for
    # users 1 and 3 on films 2 and 3 (their history is film 0), so nothing is recommended; user 2
    # (history: Telugu film 2) gets film 3 from content and hits: 1 of 3. The all-films weights
    # (popularity) would hit all three.
    assert result.loc[("telugu", "hybrid"), "recall_at_k"] == pytest.approx(1 / 3)
    # users with no Telugu film in their history: users 1 and 3
    assert result.loc[("telugu_first_time", "popularity"), "users"] == 2
    assert result.loc[("telugu_first_time", "hybrid"), "recall_at_k"] == 0.0


# ---- bridge, spread, fill examples -------------------------------------------------------------


def test_bridge_table_recommends_only_the_other_language(make_frame, make_movie):
    films = clean.clean_movies(
        make_frame(
            make_movie(
                1,
                imdb_id="tt1375666",
                title="Seed EN",
                overview="a thief enters dreams",
                genres="Action",
            ),
            make_movie(
                2, title="Same language twin", overview="a thief enters dreams", genres="Action"
            ),
            make_movie(
                3,
                language="te",
                title="Telugu match",
                overview="a thief enters dreams",
                genres="Action",
            ),
            make_movie(
                4,
                language="te",
                title="Telugu other",
                overview="village wedding comedy",
                genres="Comedy",
            ),
            make_movie(
                5,
                language="te",
                imdb_id="tt8178634",
                title="Seed TE",
                overview="village wedding feast",
                genres="Comedy",
            ),
        ),
        min_df=1,
    )
    table = pipeline.bridge_table(films, build_item_matrix(films, min_df=1), k=5)
    from_en = table[table["if_you_liked"] == "Seed EN"]
    assert from_en["try_this"].tolist() == ["Telugu match"]
    assert from_en["language"].tolist() == ["Telugu"]
    assert from_en["shared_genres"].tolist() == ["Action"]
    from_te = table[table["if_you_liked"] == "Seed TE"]
    assert set(from_te["language"]) <= {"English"}
    assert "Telugu other" not in from_te["try_this"].tolist()


def test_bridge_table_lists_a_repeated_title_once(make_frame, make_movie):
    """Found on the real run: one film listed four times under different ids."""
    plot = "a thief enters dreams"
    films = clean.clean_movies(
        make_frame(
            make_movie(1, imdb_id="tt1375666", title="Seed EN", overview=plot, genres="Action"),
            make_movie(2, language="te", title="Twice", overview=plot, genres="Action"),
            make_movie(3, language="te", title="Twice", overview=plot, genres="Action"),
            make_movie(4, language="te", title="Once", overview=plot, genres="Action"),
        ),
        min_df=1,
    )
    table = pipeline.bridge_table(films, build_item_matrix(films, min_df=1), k=5)
    assert sorted(table["try_this"]) == ["Once", "Twice"]
    assert table["rank"].tolist() == [1, 2]


def test_bridge_table_lists_at_most_k_films_with_a_hand_derived_similarity(make_frame, make_movie):
    plot = "a thief enters dreams"
    films = clean.clean_movies(
        make_frame(
            make_movie(
                1, imdb_id="tt1375666", title="Seed", overview=plot, genres="Action", keywords=None
            ),
            *[
                make_movie(
                    i,
                    language="te",
                    title=f"T{i}",
                    overview=plot,
                    genres="Action",
                    keywords=None,
                )
                for i in (2, 3, 4)
            ],
        ),
        min_df=1,
    )
    table = pipeline.bridge_table(films, build_item_matrix(films, min_df=1), k=2)
    assert table["rank"].tolist() == [1, 2]
    assert table["try_this"].tolist() == ["T2", "T3"]  # equal scores: lower index first
    # identical text (block weight 1.0 -> 1.0) and identical genres (0.6 * 0.6) over the squared
    # full block length 1 + 0.36 + 0.36 = 1.72, and no shared people: (1.0 + 0.36) / 1.72
    assert table["similarity"].tolist() == [0.791, 0.791]


def test_like_spread_counts_shelf_likes_most_liked_first(make_frame, make_movie):
    films = make_frame(
        make_movie(1, title="English hit"),
        make_movie(2, language="te", title="Big"),
        make_movie(3, language="te", title="Small"),
        make_movie(4, language="te", title="Unliked"),
    )
    relevant = csr([[1, 1, 0, 0], [1, 1, 1, 0], [1, 1, 0, 0], [0, 1, 0, 0]])
    shelf = (films["language"] == "te").to_numpy()
    table = pipeline.like_spread(relevant, shelf, films)
    assert table["title"].tolist() == ["Big", "Small"]
    assert table["test_likes"].tolist() == [4, 1]
    assert table["share_pct"].tolist() == [80.0, 20.0]
    assert table["cumulative_pct"].tolist() == [80.0, 100.0]
    assert table["films_liked_in_total"].tolist() == [2, 2]
    assert pipeline.like_spread(relevant, shelf, films, top=1)["cumulative_pct"].tolist() == [80.0]


def test_like_spread_rounds_to_one_decimal(make_frame, make_movie):
    films = make_frame(*[make_movie(i, language="te") for i in (1, 2, 3)])
    relevant = csr([[1, 0, 0], [1, 1, 0], [1, 0, 1]])  # film 1 has 3 of 5 likes, 2 and 3 one each
    table = pipeline.like_spread(relevant, np.ones(3, dtype=bool), films)
    assert table["share_pct"].tolist() == [60.0, 20.0, 20.0]
    third = pipeline.like_spread(csr([[1, 1, 1]]), np.ones(3, dtype=bool), films)
    assert third["share_pct"].tolist() == [33.3, 33.3, 33.3]  # 100 / 3
    assert third["cumulative_pct"].tolist() == [33.3, 66.7, 100.0]


def test_like_spread_with_no_likes_is_an_empty_table(make_frame, make_movie):
    films = make_frame(make_movie(1, language="te"))
    table = pipeline.like_spread(
        sparse.csr_matrix((2, 1), dtype=np.float32), np.array([True]), films
    )
    assert len(table) == 0
    assert "cumulative_pct" in table.columns


def test_fill_examples_lists_the_gappiest_telugu_films_and_marks_filled_values(
    make_frame, make_movie
):
    rows = [
        make_movie(i, language="te", runtime_min=150, release_year=2010, genres="Action")
        for i in (1, 2)
    ]
    rows.append(
        make_movie(
            3,
            language="te",
            title=None,
            original_title="సీత",
            genres=None,
            runtime_min=None,
            overview=None,
            keywords=None,
            release_year=None,
        )
    )
    rows.append(make_movie(4, language="en", genres=None))
    out = clean.clean_movies(make_frame(*rows), min_df=1)
    table = pipeline.fill_examples(out, n=2)
    # film 3 has five gaps (genres, runtime, overview, keywords, year); films 1 and 2 none and
    # tie on votes, so the lower id goes first; the English film with a gap is not listed
    assert table["title"].tolist()[0] == "సీత"
    assert table["gaps_filled"].tolist() == [5, 0]
    assert table["original_title"].tolist() == ["సీత", "Film 1"]
    first, second = table.iloc[0], table.iloc[1]
    for col in ("genres", "runtime_min", "release_year", "keywords", "overview"):
        assert first[col].endswith(" (filled)"), col
        assert not second[col].endswith("(filled)"), col


# ---- findings and limits -----------------------------------------------------------------------


def scope_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "language": ["te", "en"],
            "landed_rows": [30, 100],
            "duplicate_rows": [1, 4],
            "adult_titles": [0, 2],
            "below_vote_floor": [0, 54],
            "kept": [29, 40],
        }
    )


def audit_frame(after: tuple[int, int] = (0, 0)) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "language": ["te", "en"],
            "column_name": ["genres", "genres"],
            "total_rows": [29, 40],
            "missing_before": [7, 3],
            "missing_after": list(after),
            "missing_before_pct": [24.1, 7.5],
        }
    )


QUALITY = pd.DataFrame(
    {
        "column_name": ["genres"],
        "language": ["te"],
        "metric": ["share with no correct genre"],
        "masked_rows": [2],
        "fill_error": [0.5],
        "naive_error": [1.0],
    }
)
COVERAGE = pd.DataFrame(
    {
        "language": ["te", "en"],
        "movies": [29, 40],
        "movies_with_ratings": [3, 38],
        "ratings": [11, 9000],
    }
)
SPREAD = pd.DataFrame(
    {
        "title": ["Hit One", "Hit Two", "Hit Three", "Small"],
        "test_likes": [50, 30, 10, 5],
        "share_pct": [52.6, 31.6, 10.5, 5.3],
        "cumulative_pct": [52.6, 84.2, 94.7, 100.0],
        "films_liked_in_total": [9, 9, 9, 9],
    }
)
WEIGHTS = {
    "all films": {"item_item": 0.75, "content": 0.25, "popularity": 0.0},
    "Telugu shelf": {"item_item": 0.0, "content": 0.5, "popularity": 0.5},
}


def methods(slice_name: str, recall: list[float], ndcg: list[float], users: int = 77):
    names = ["popularity", "content", "hybrid"][: len(recall)]
    return pd.DataFrame(
        {
            "slice": slice_name,
            "method": names,
            "users": users,
            "recall_at_k": recall,
            "ndcg_at_k": ndcg,
        }
    )


MANY = 1_000_000  # 1/sqrt(users) = 0.001, below the fixed 0.005 margin


def make_findings(result: pd.DataFrame, **over) -> str:
    args = {
        "staged_rows": 29 + 40,
        "cleaned_rows": 29 + 40,
        "excluded": {"validation": 12, "test": 5},
        "val_users": {"all films": 900, "Telugu shelf": 14},
        "weight_fallback": False,
        "min_val_users": 30,
        **over,
    }
    return " | ".join(
        pipeline.findings(
            scope_frame(),
            args.pop("audit", audit_frame()),
            QUALITY,
            COVERAGE,
            result,
            WEIGHTS,
            args.pop("spread", SPREAD),
            10,
            **args,
        )
    )


def test_findings_are_built_from_the_tables_they_describe():
    result = pd.concat(
        [
            methods("all", [0.111, 0.150, 0.222], [0.05, 0.06, 0.09]),
            pd.DataFrame(
                {
                    "slice": ["telugu"] * 2,
                    "method": ["popularity", "hybrid"],
                    "users": [0, 0],
                    "recall_at_k": [np.nan, np.nan],
                    "ndcg_at_k": [np.nan, np.nan],
                }
            ),
        ]
    )
    text = make_findings(result)
    assert "29 Telugu and 40 English films" in text
    assert "(130 rows landed;" in text
    assert "genres 7 of 29 (24.1%)" in text
    assert "0.50 vs 1.00" in text
    assert "3 of 29 Telugu films" in text
    assert "all films (77 test users)" in text
    assert "Recall@10: popularity 0.111, content 0.150, hybrid 0.222" in text
    assert "NDCG@10: popularity 0.050, content 0.060, hybrid 0.090" in text
    assert "Telugu films only: no test users, nothing measured." in text


def test_findings_name_a_winner_only_with_the_best_recall_and_ndcg_and_a_clear_lead():
    clear = methods("all", [0.10, 0.12, 0.20], [0.05, 0.06, 0.09], users=MANY)
    assert "Best: hybrid" in make_findings(clear)
    assert "No clear winner" not in make_findings(clear)
    # best recall but not best NDCG
    split = methods("all", [0.10, 0.12, 0.20], [0.05, 0.10, 0.09], users=MANY)
    assert "Best:" not in make_findings(split)
    assert "no clear winner" in make_findings(split)
    # best on both, but the recall lead over the runner-up (0.003) is under the 0.005 margin
    narrow = methods("all", [0.10, 0.197, 0.200], [0.05, 0.06, 0.09], users=MANY)
    assert "Best:" not in make_findings(narrow)
    assert "no clear winner" in make_findings(narrow)
    assert str(pipeline.BEST_RECALL_MARGIN) in make_findings(narrow)
    # every method's numbers are listed whether or not there is a winner
    assert "hybrid 0.200" in make_findings(narrow)
    assert "NDCG@10: popularity 0.050, content 0.060, hybrid 0.090" in make_findings(narrow)


def test_a_recall_lead_of_exactly_the_margin_counts_even_with_float_noise():
    # 0.102 - 0.097 is 0.0049999999999999906 in floating point, and is a lead of 0.005
    exact = methods("all", [0.097, 0.102], [0.05, 0.06], users=MANY)
    assert "Best: content" in make_findings(exact)


def test_a_small_slice_needs_a_recall_lead_of_one_over_root_users():
    # 40 users: margin = 1/sqrt(40) = 0.158. A 0.006 lead is one user's single hit, not a winner.
    small = methods("telugu", [0.050, 0.056], [0.05, 0.06], users=40)
    text = make_findings(small)
    assert "Best:" not in text
    assert "no clear winner" in text
    assert "0.158" in text
    # 10,000 users: margin = 0.01. A lead of 0.008 is under it, 0.012 is over it.
    assert "Best:" not in make_findings(methods("all", [0.100, 0.108], [0.05, 0.06], users=10_000))
    assert "Best: content" in make_findings(
        methods("all", [0.100, 0.112], [0.05, 0.06], users=10_000)
    )
    # 4 users: margin 0.5. A lead of exactly 0.5 counts.
    assert "Best: content" in make_findings(methods("all", [0.25, 0.75], [0.05, 0.06], users=4))


def test_a_tie_on_the_best_recall_is_no_clear_winner():
    tie = methods("all", [0.2, 0.2], [0.05, 0.06])
    assert "no clear winner" in make_findings(tie)


def test_findings_state_only_measured_facts_about_the_like_spread():
    text = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]))
    assert "Hit One" in text
    assert "52.6%" in text  # the most-liked film's share
    assert "top 3 (Hit One, Hit Two, Hit Three) hold 94.7%" in text
    assert "9 distinct" in text
    assert "That is why" not in text
    assert "hard to beat" not in text


def test_findings_with_no_telugu_likes_leave_the_spread_sentence_out():
    empty = SPREAD.iloc[0:0]
    text = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]), spread=empty)
    assert "Telugu test likes" not in text


def test_findings_compute_dropped_rows_and_report_what_is_still_missing():
    ok = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]), audit=audit_frame((1, 2)))
    assert "filled 10 missing values and dropped 0 rows" in ok
    assert "3 values are still missing" in ok
    lost = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]), staged_rows=75, cleaned_rows=69)
    assert "dropped 6 rows" in lost


def test_findings_describe_duplicates_as_extra_copies_not_scope():
    text = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]))
    assert "5 rows are extra copies of an id (one copy of each id is kept)" in text
    assert "repeated ids" not in text
    assert "2 adult titles and 54 English films under the vote floor are left out" in text


def test_findings_say_how_many_films_each_window_left_out_of_the_candidates():
    text = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]))
    assert "12 films for validation and 5 for test" in text


def test_findings_print_validation_users_next_to_each_shelf_s_weights():
    text = make_findings(methods("all", [0.1, 0.2], [0.1, 0.2]))
    assert "all films (900 validation users): item_item 0.75, content 0.25, popularity 0.0" in text
    assert "Telugu shelf (14 validation users): item_item 0.0, content 0.5, popularity 0.5" in text
    assert "fewer than" not in text


def test_findings_say_when_the_telugu_shelf_fell_back_to_the_all_films_weights():
    text = make_findings(
        methods("all", [0.1, 0.2], [0.1, 0.2]), weight_fallback=True, min_val_users=30
    )
    assert (
        "Telugu shelf has 14 validation users, fewer than 30, so it uses the all-films weights"
        in text
    )


def test_limits_state_the_measured_telugu_counts_and_the_vote_snapshot():
    limits = " | ".join(
        pipeline.limit_notes(
            Settings(),
            telugu_test_users=63,
            telugu_val_users=14,
            telugu_rated_films=3,
            telugu_films=29,
        )
    )
    assert "63 Telugu test users, 14 Telugu validation users" in limits
    assert "3 of 29 Telugu films have any rating" in limits
    assert "within noise" not in limits
    assert "2024 snapshot" in limits
    assert "every method" in limits
    assert "1-in-8 sample" in limits
    assert "popularity counts every user" in limits
    assert "filled genres" in limits.lower()


# ---- charts ------------------------------------------------------------------------------------


def assert_png(path, minimum: int = 4000) -> None:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > minimum


def test_chart_missing_writes_a_png(tmp_path):
    audit = pd.DataFrame(
        {
            "language": ["te", "te", "en", "en"],
            "column_name": ["genres", "runtime_min", "genres", "runtime_min"],
            "total_rows": [10, 10, 20, 20],
            "missing_before": [5, 2, 4, 1],
            "missing_after": [0, 0, 1, 0],
            "missing_before_pct": [50.0, 20.0, 20.0, 5.0],
        }
    )
    pipeline.chart_missing(audit, tmp_path / "missing.png")
    assert_png(tmp_path / "missing.png")


def test_chart_eval_writes_a_png(tmp_path):
    result = pd.concat(
        [
            methods("all", [0.1, 0.2], [0.1, 0.2]).assign(method=["popularity", "hybrid"]),
            methods("telugu", [0.3, 0.1], [0.1, 0.2]).assign(method=["popularity", "hybrid"]),
        ]
    )
    pipeline.chart_eval(result, 10, tmp_path / "eval.png")
    assert_png(tmp_path / "eval.png")


def test_chart_fill_quality_writes_a_png(tmp_path):
    rows = [
        {
            "column_name": col,
            "language": lang,
            "metric": "mean abs error",
            "masked_rows": 5,
            "fill_error": 1.0,
            "naive_error": 2.0,
        }
        for col in ("runtime_min", "release_year", "genres")
        for lang in ("all", "en", "te")
    ]
    pipeline.chart_fill_quality(pd.DataFrame(rows), tmp_path / "quality.png")
    assert_png(tmp_path / "quality.png")
