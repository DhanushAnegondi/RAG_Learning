"""Time split and ranking metrics, with hand-computed expectations."""

import math

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from cinebridge import evaluate as ev


def ratings(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["user_id", "movie_id", "rating", "rated_at"])
    df["rated_at"] = pd.to_datetime(df["rated_at"])
    return df


def csr(rows: list[list[int]]) -> sparse.csr_matrix:
    return sparse.csr_matrix(np.array(rows, dtype=np.float32))


def test_split_is_strict_at_the_cutoff():
    df = ratings(
        [
            (1, 10, 4.0, "2023-01-01 00:00:00"),
            (1, 11, 4.0, "2022-12-31 23:59:59"),
            (1, 12, 4.0, "2023-06-01 00:00:00"),
        ]
    )
    train, test = ev.split_by_time(df, pd.Timestamp("2023-01-01"))
    assert train["movie_id"].tolist() == [11]
    assert test["movie_id"].tolist() == [10, 12]


def test_window_keeps_start_and_leaves_out_end():
    df = ratings(
        [(1, 10, 4.0, "2022-01-01"), (1, 11, 4.0, "2022-12-31"), (1, 12, 4.0, "2023-01-01")]
    )
    got = ev.window(df, pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01"))
    assert got["movie_id"].tolist() == [10, 11]


def test_user_matrices_split_likes_seen_and_later_likes():
    train = ratings(
        [
            (1, 10, 5.0, "2020-01-01"),
            (1, 11, 2.0, "2020-01-02"),
            (2, 10, 4.0, "2020-01-01"),
            (3, 99, 5.0, "2020-01-01"),  # unknown movie id: ignored
        ]
    )
    test = ratings(
        [(1, 12, 4.0, "2021-01-01"), (1, 10, 5.0, "2021-01-02"), (2, 12, 3.0, "2021-01-01")]
    )
    users, profile, seen, relevant = ev.user_matrices(
        train, test, [10, 11, 12], like=4.0, min_profile=1
    )
    assert users.tolist() == [1]
    assert profile.toarray().tolist() == [[1.0, 0.0, 0.0]]
    assert seen.toarray().tolist() == [[1.0, 1.0, 0.0]]
    # movie 10 was already rated in train, so it cannot be a later hit
    assert relevant.toarray().tolist() == [[0.0, 0.0, 1.0]]


def test_user_matrices_need_enough_liked_films_in_the_profile():
    train = ratings(
        [(1, 10, 5.0, "2020-01-01"), (2, 10, 5.0, "2020-01-01"), (2, 11, 4.0, "2020-01-01")]
    )
    test = ratings([(1, 12, 5.0, "2021-01-01"), (2, 12, 5.0, "2021-01-01")])
    users, *_ = ev.user_matrices(train, test, [10, 11, 12], like=4.0, min_profile=2)
    assert users.tolist() == [2]


def test_recall_and_ndcg_by_hand():
    recs = np.array([[5, 2, 9]])
    valid = np.ones((1, 3), dtype=bool)
    relevant = csr([[0, 0, 1, 0, 0, 0, 0, 1, 0, 1]])  # items 2, 7, 9
    recall, ndcg, hit = ev.rank_metrics(recs, valid, relevant)
    assert recall.tolist() == pytest.approx([2 / 3])
    dcg = 1 / math.log2(3) + 1 / math.log2(4)
    ideal = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert ndcg.tolist() == pytest.approx([dcg / ideal])
    assert hit.tolist() == [1.0]


def test_ndcg_ideal_is_capped_by_the_number_of_relevant_items():
    recs = np.array([[4, 0, 1]])
    valid = np.ones((1, 3), dtype=bool)
    relevant = csr([[0, 0, 0, 0, 1]])
    recall, ndcg, _ = ev.rank_metrics(recs, valid, relevant)
    assert recall.tolist() == [1.0]
    assert ndcg.tolist() == pytest.approx([1.0])


def test_unfilled_slots_never_count_as_hits():
    recs = np.array([[2, 0]])
    valid = np.array([[False, True]])
    relevant = csr([[0, 0, 1]])
    recall, ndcg, hit = ev.rank_metrics(recs, valid, relevant)
    assert (recall.tolist(), ndcg.tolist(), hit.tolist()) == ([0.0], [0.0], [0.0])


def toy():
    """4 items: 0,1 English, 2,3 Telugu. Three users."""
    profile = csr([[1, 0, 0, 0], [0, 1, 0, 0], [1, 0, 1, 0]])
    seen = profile.copy()
    relevant = csr([[0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]])
    telugu = np.array([False, False, True, True])
    return profile, seen, relevant, telugu


def always(order: list[int]):
    """A scorer that ranks items in a fixed order for every user."""
    row = np.zeros(len(order), dtype=np.float32)
    for rank, item in enumerate(order):
        row[item] = len(order) - rank
    return lambda p: np.tile(row, (p.shape[0], 1))


PARTS = {"a": always([3, 2, 1, 0]), "b": always([0, 1, 2, 3])}
SOLO = {"a": {"a": 1.0}, "b": {"b": 1.0}}
ALL4 = np.ones(4, dtype=bool)


def test_evaluate_reports_each_method_on_the_same_users():
    profile, seen, relevant, telugu = toy()
    out = ev.evaluate(PARTS, SOLO, profile, seen, relevant, {"all": (ALL4, None)}, k=1)
    got = out.set_index("method")
    assert got["users"].tolist() == [3, 3]
    # a: u0 gets item 3 (hit, 1 of 2), u1 gets 3 (miss), u2 gets 3 (hit, 1 of 1)
    assert got.loc["a", "recall_at_k"] == pytest.approx((0.5 + 0 + 1) / 3)
    assert got.loc["a", "hit_rate"] == pytest.approx(2 / 3)
    # b: u0 has seen 0 so gets 1 (hit), u1 has seen 1 so gets 0 (miss), u2 gets 1 (miss)
    assert got.loc["b", "recall_at_k"] == pytest.approx((0.5 + 0 + 0) / 3)


def test_slice_limits_candidates_and_hits_for_every_method():
    profile, seen, relevant, telugu = toy()
    out = ev.evaluate(
        PARTS, {"b": {"b": 1.0}}, profile, seen, relevant, {"telugu": (telugu, None)}, k=1
    )
    row = out.iloc[0]
    # English items cannot be recommended here: u0 gets 2 (miss; wants 3), u1 gets 2 (hit),
    # u2 has seen 2 so gets 3 (hit)
    assert row["users"] == 3
    assert row["recall_at_k"] == pytest.approx(2 / 3)


def test_slice_user_mask_and_users_without_a_relevant_item_are_left_out():
    profile, seen, relevant, telugu = toy()
    relevant = csr([[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])  # u0 wants no Telugu film
    no_telugu_history = np.array([True, True, False])
    out = ev.evaluate(
        PARTS,
        {"b": {"b": 1.0}},
        profile,
        seen,
        relevant,
        {"bridge": (telugu, no_telugu_history)},
        k=1,
    )
    row = out.iloc[0]
    assert row["users"] == 1  # only u1
    assert row["recall_at_k"] == pytest.approx(1.0)


def test_evaluate_blends_parts_with_the_given_weights():
    profile, seen, relevant, telugu = toy()
    # 0.6 * a + 0.4 * b: a scores [1,2,3,4]/4, b scores [4,3,2,1]/4 over all films
    # -> item 3 = 0.6 + 0.1 is the top pick, so the blend ranks like a
    out = ev.evaluate(
        PARTS,
        {"mix": {"a": 0.6, "b": 0.4}, "a": {"a": 1.0}},
        profile,
        seen,
        relevant,
        {"all": (ALL4, None)},
        k=1,
    ).set_index("method")
    assert out.loc["mix", "recall_at_k"] == pytest.approx(out.loc["a", "recall_at_k"])
    flipped = ev.evaluate(
        PARTS, {"mix": {"a": 0.4, "b": 0.6}}, profile, seen, relevant, {"all": (ALL4, None)}, k=1
    )
    assert flipped["recall_at_k"].iloc[0] == pytest.approx((0.5 + 0 + 0) / 3)


def test_evaluate_gives_the_same_answer_in_small_batches():
    profile, seen, relevant, telugu = toy()
    slices = {"all": (ALL4, None), "telugu": (telugu, None)}
    methods = {"a": {"a": 1.0}, "mix": {"a": 0.5, "b": 0.5}}
    one = ev.evaluate(PARTS, methods, profile, seen, relevant, slices, k=2, batch=1)
    big = ev.evaluate(PARTS, methods, profile, seen, relevant, slices, k=2, batch=100)
    pd.testing.assert_frame_equal(one, big)


def fixed(row: list[float]):
    return lambda p: np.tile(np.array(row, dtype=np.float32), (p.shape[0], 1))


ALL3 = np.ones(3, dtype=bool)


def test_choose_weights_picks_the_best_blend_and_reports_every_candidate():
    profile = csr([[1, 0, 0]])
    relevant = csr([[0, 0, 1]])
    parts = {"cf": fixed([0, 0.0, 1.0]), "content": fixed([0, 1.0, 0.0])}
    grid = [
        {"cf": 0.0, "content": 1.0},
        {"cf": 0.25, "content": 0.75},
        {"cf": 0.75, "content": 0.25},
    ]
    best, table = ev.choose_weights(parts, grid, profile, profile.copy(), relevant, ALL3, k=1)
    assert best == {"cf": 0.75, "content": 0.25}
    assert table["cf"].tolist() == [0.0, 0.25, 0.75]
    assert table["recall_at_k"].tolist() == [0.0, 0.0, 1.0]
    assert table["users"].tolist() == [1, 1, 1]


def test_choose_weights_tie_goes_to_the_first_grid_entry():
    profile = csr([[1, 0, 0]])
    relevant = csr([[0, 0, 1]])
    parts = {"cf": fixed([0, 0.0, 1.0]), "content": fixed([0, 0.0, 1.0])}
    grid = [{"cf": 0.5, "content": 0.5}, {"cf": 1.0, "content": 0.0}]
    best, _ = ev.choose_weights(parts, grid, profile, profile.copy(), relevant, ALL3, k=1)
    assert best == {"cf": 0.5, "content": 0.5}


def test_choose_weights_scores_only_users_with_a_relevant_candidate():
    profile = csr([[1, 0, 0, 0], [1, 0, 0, 0]])
    relevant = csr([[0, 1, 0, 0], [0, 0, 0, 1]])  # only the second user wants a shelf film
    shelf = np.array([False, False, True, True])
    parts = {"cf": fixed([0, 9.0, 1.0, 2.0])}
    best, table = ev.choose_weights(
        parts, [{"cf": 1.0}], profile, profile.copy(), relevant, shelf, k=1
    )
    assert table["users"].tolist() == [1]
    assert table["recall_at_k"].tolist() == [1.0]


def test_choose_weights_with_nobody_to_score_returns_the_first_entry():
    profile = csr([[1, 0, 0]])
    relevant = csr([[0, 0, 0]])
    grid = [{"cf": 0.25}, {"cf": 1.0}]
    parts = {"cf": fixed([0, 1.0, 2.0])}
    best, table = ev.choose_weights(parts, grid, profile, profile.copy(), relevant, ALL3, k=1)
    assert best == {"cf": 0.25}
    assert table["users"].tolist() == [0, 0]


def test_a_repeated_user_film_pair_is_still_one_entry():
    train = ratings([(1, 10, 5.0, "2020-01-01"), (1, 10, 4.0, "2020-01-02")])
    test = ratings([(1, 11, 4.0, "2021-01-01"), (1, 11, 5.0, "2021-01-02")])
    _, profile, seen, relevant = ev.user_matrices(train, test, [10, 11], like=4.0, min_profile=1)
    assert profile.toarray().tolist() == [[1.0, 0.0]]
    assert seen.toarray().tolist() == [[1.0, 0.0]]
    assert relevant.toarray().tolist() == [[0.0, 1.0]]


def test_test_ratings_of_films_outside_the_catalogue_are_ignored():
    train = ratings([(1, 10, 5.0, "2020-01-01")])
    test = ratings([(1, 99, 5.0, "2021-01-01"), (1, 11, 4.0, "2021-01-02")])
    _, _, _, relevant = ev.user_matrices(train, test, [10, 11], like=4.0, min_profile=1)
    assert relevant.toarray().tolist() == [[0.0, 1.0]]


def test_pair_key_keeps_film_ids_above_two_to_the_twenty_apart():
    """user 2 + film 1 and user 1 + film 2**20 + 1 share a key if the film id gets only 20 bits."""
    big = (1 << 20) + 1
    train = ratings([(1, 1, 5.0, "2020-01-01"), (2, 1, 5.0, "2020-01-01")])
    test = ratings([(1, big, 4.0, "2021-01-01")])
    users, _, _, relevant = ev.user_matrices(train, test, [1, big], like=4.0, min_profile=1)
    assert users.tolist() == [1]
    assert relevant.toarray().tolist() == [[0.0, 1.0]]


def test_recall_divides_by_every_relevant_item_not_by_k():
    recs = np.array([[1, 3]])
    valid = np.ones((1, 2), dtype=bool)
    relevant = csr([[0, 1, 0, 1, 1, 1]])  # four relevant, two found
    recall, ndcg, _ = ev.rank_metrics(recs, valid, relevant)
    assert recall.tolist() == pytest.approx([0.5])  # 2 / 4, not 2 / k
    assert ndcg.tolist() == pytest.approx([1.0])  # both slots hold hits: DCG equals the ideal


def test_hit_rate_counts_a_user_once_however_many_hits():
    recs = np.array([[0, 1, 2]])
    relevant = csr([[1, 1, 1]])
    _, _, hit = ev.rank_metrics(recs, np.ones((1, 3), dtype=bool), relevant)
    assert hit.tolist() == [1.0]


def test_a_zero_weight_part_that_no_method_uses_is_not_scored():
    profile, seen, relevant, _ = toy()
    parts = {"b": PARTS["b"]}  # no scorer "a" exists: asking for it would raise KeyError
    out = ev.evaluate(
        parts, {"only_b": {"a": 0.0, "b": 1.0}}, profile, seen, relevant, {"all": (ALL4, None)}, k=1
    )
    assert out["recall_at_k"].iloc[0] == pytest.approx(
        0.5 / 3
    )  # same as b alone (b: u0 hit 1 of 2; u1, u2 miss)


def test_a_slice_nobody_qualifies_for_reports_nan_not_zero():
    profile, seen, _, telugu = toy()
    relevant = csr([[0, 1, 0, 0], [0, 1, 0, 0], [0, 1, 0, 0]])  # nobody wants a Telugu film
    out = ev.evaluate(PARTS, SOLO, profile, seen, relevant, {"telugu": (telugu, None)}, k=1)
    assert out["users"].tolist() == [0, 0]
    assert out["recall_at_k"].isna().all()


def test_users_count_only_those_with_a_relevant_item_in_the_slice():
    profile, seen, _, telugu = toy()
    relevant = csr([[0, 0, 0, 1], [0, 1, 0, 0], [0, 0, 1, 0]])  # u1 wants only an English film
    out = ev.evaluate(PARTS, {"a": {"a": 1.0}}, profile, seen, relevant, {"t": (telugu, None)}, k=1)
    assert out["users"].tolist() == [2]


def test_evaluate_never_recommends_a_film_the_user_rated_and_disliked():
    """seen holds every rated film; profile only the liked ones. They must not be swapped."""
    profile = csr([[1, 0, 0, 0]])
    seen = csr([[1, 1, 0, 0]])  # film 1 was rated low: seen, not in the profile
    relevant = csr([[0, 0, 1, 0]])
    parts = {"b": always([0, 1, 2, 3])}
    out = ev.evaluate(parts, {"b": {"b": 1.0}}, profile, seen, relevant, {"all": (ALL4, None)}, k=1)
    assert out["recall_at_k"].iloc[0] == 1.0  # top unseen film is 2
    _, table = ev.choose_weights(parts, [{"b": 1.0}], profile, seen, relevant, ALL4, k=1)
    assert table["recall_at_k"].tolist() == [1.0]


def test_the_blend_scale_ignores_a_seen_film_with_the_top_score():
    """The user's seen film 0 has a huge cf score. Scaling by it would shrink cf to nothing and
    let content pick film 1; scaling by the best unseen film lets cf pull film 2 ahead."""
    profile = csr([[0, 0, 0]])  # the user liked nothing, but did rate (and so has seen) film 0
    seen = csr([[1, 0, 0]])
    relevant = csr([[0, 0, 1]])
    parts = {"cf": fixed([100.0, 2.0, 3.0]), "content": fixed([0.0, 0.9, 0.72])}
    # best unseen: cf 3 -> [_, 0.667, 1.0], content 0.9 -> [_, 1.0, 0.8]
    # half each: film 1 = 0.333 + 0.5 = 0.833, film 2 = 0.5 + 0.4 = 0.9 -> film 2 (a hit)
    # scaled by the seen film instead: film 1 = 0.01 + 0.5, film 2 = 0.015 + 0.4 -> film 1 (miss)
    grid = [{"cf": 0.5, "content": 0.5}]
    _, table = ev.choose_weights(parts, grid, profile, seen, relevant, ALL3, k=1)
    assert table["recall_at_k"].tolist() == [1.0]


def test_a_zero_score_pick_is_not_a_hit():
    """Nothing scores above zero for the user, so no film is recommended at all."""
    profile = csr([[0, 0, 0, 1]])
    relevant = csr([[1, 0, 0, 0]])
    parts = {"z": fixed([0.0, 0.0, 0.0, 0.0])}
    out = ev.evaluate(
        parts, {"z": {"z": 1.0}}, profile, profile.copy(), relevant, {"all": (ALL4, None)}, k=1
    )
    assert out["recall_at_k"].iloc[0] == 0.0
