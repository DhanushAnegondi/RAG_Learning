"""Scoring and ranking, on matrices small enough to check by hand."""

import numpy as np
import pytest
from scipy import sparse

from cinebridge import recommend as rec


def likes(rows: list[list[int]]) -> sparse.csr_matrix:
    return sparse.csr_matrix(np.array(rows, dtype=np.float32))


def test_popularity_counts_likes_per_item():
    m = likes([[1, 0, 1], [1, 0, 0], [1, 1, 0]])
    assert rec.popularity_scores(m).tolist() == [3.0, 1.0, 1.0]


def test_item_neighbors_is_cosine_of_shared_likes():
    # item0 liked by u0,u1,u2,u3; item1 by u0,u1; item2 by u3; item3 by nobody
    m = likes([[1, 1, 0, 0], [1, 1, 0, 0], [1, 0, 0, 0], [1, 0, 1, 0]])
    s = rec.item_neighbors(m, top_n=3, shrink=0.0).toarray()
    assert s[0, 1] == pytest.approx(2 / np.sqrt(4 * 2))
    assert s[1, 0] == pytest.approx(2 / np.sqrt(4 * 2))
    assert s[0, 2] == pytest.approx(1 / np.sqrt(4 * 1))
    assert s[1, 2] == 0.0
    assert np.diag(s).tolist() == [0.0, 0.0, 0.0, 0.0]
    assert s[3].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert np.isfinite(s).all()


def test_item_neighbors_shrink_pulls_thin_evidence_down():
    m = likes([[1, 1, 0, 0], [1, 1, 0, 0], [1, 0, 0, 0], [1, 0, 1, 0]])
    s = rec.item_neighbors(m, top_n=3, shrink=2.0).toarray()
    assert s[0, 1] == pytest.approx(2 / (np.sqrt(8) + 2.0))
    assert s[0, 2] == pytest.approx(1 / (np.sqrt(4) + 2.0))


def test_item_neighbors_keeps_only_the_top_n_per_item_and_blocks_agree():
    rng = np.random.default_rng(1)
    m = sparse.csr_matrix((rng.random((40, 12)) < 0.4).astype(np.float32))
    full = rec.item_neighbors(m, top_n=11, shrink=0.0, block=5).toarray()
    top2 = rec.item_neighbors(m, top_n=2, shrink=0.0, block=7)
    assert (np.diff(top2.indptr) <= 2).all()
    for i in range(12):
        kept = top2[i].toarray().ravel()
        best = np.sort(full[i])[::-1][:2]
        assert np.sort(kept)[::-1][:2] == pytest.approx(best)


def test_cf_scores_read_row_i_as_the_neighbours_of_liked_item_i():
    # asymmetric on purpose: row 0 says film 1 is a neighbour of film 0 (0.5), but row 1 does not
    # say film 0 is a neighbour of film 1; a transposed product would swap these answers
    s = sparse.csr_matrix(np.array([[0, 0.5, 0], [0, 0, 0.2], [0.4, 0, 0]], dtype=np.float32))
    p = likes([[1, 0, 0], [0, 1, 1]])
    got = rec.cf_scores(p, s)
    assert got[0] == pytest.approx([0.0, 0.5, 0.0])  # liked film 0 -> row 0
    assert got[1] == pytest.approx([0.4, 0.0, 0.2])  # liked films 1 and 2 -> rows 1 + 2 summed


def test_content_scores_are_cosine_to_the_mean_liked_vector():
    x = sparse.csr_matrix(np.array([[1, 0], [0, 1], [0.6, 0.8], [1, 0]], dtype=np.float32))
    p = likes([[1, 1, 0, 0], [0, 0, 0, 0]])
    got = rec.content_scores(p, x)
    # profile = normalised (1,1) = (0.7071, 0.7071)
    assert got[0] == pytest.approx([0.70711, 0.70711, 0.98995, 0.70711], abs=1e-4)
    assert got[1].tolist() == [0.0, 0.0, 0.0, 0.0]


EVERY = np.ones(3, dtype=bool)
NOTHING_SEEN = sparse.csr_matrix((2, 3), dtype=np.float32)


def test_blend_endpoints_and_row_scaling():
    parts = {
        "cf": np.array([[0.0, 2.0, 4.0], [0.0, 0.0, 0.0]], dtype=np.float32),
        "content": np.array([[0.5, 0.25, 0.0], [0.2, 0.1, 0.0]], dtype=np.float32),
    }
    assert rec.blend(parts, {"cf": 1.0}, EVERY, NOTHING_SEEN)[0] == pytest.approx([0.0, 0.5, 1.0])
    assert rec.blend(parts, {"content": 1.0}, EVERY, NOTHING_SEEN)[0] == pytest.approx(
        [1.0, 0.5, 0.0]
    )
    half = rec.blend(parts, {"cf": 0.5, "content": 0.5}, EVERY, NOTHING_SEEN)
    assert half[0] == pytest.approx([0.5, 0.5, 0.5])
    # a user with no collaborative signal still gets the content ranking, no NaN
    assert half[1] == pytest.approx([0.5, 0.25, 0.0])


def test_blend_scales_each_part_inside_the_candidate_set():
    """Found on the real run: scaled over all films, the item-item part vanished on the Telugu
    shelf and the hybrid followed content alone."""
    parts = {
        "cf": np.array([[10.0, 0.2, 0.1]], dtype=np.float32),
        "content": np.array([[0.0, 0.1, 1.0]], dtype=np.float32),
    }
    shelf = np.array([False, True, True])
    nothing = sparse.csr_matrix((1, 3), dtype=np.float32)
    got = rec.blend(parts, {"cf": 0.75, "content": 0.25}, shelf, nothing)
    # inside the shelf: cf -> [1.0, 0.5], content -> [0.1, 1.0]
    assert got[0, 1:] == pytest.approx([0.75 + 0.025, 0.375 + 0.25])
    assert got[0, 1] > got[0, 2]


def test_blend_scales_by_the_best_unseen_candidate():
    """The user's own seen film can score highest; it can never be recommended, so it must not
    set the scale that every recommendable film is divided by."""
    parts = {
        "cf": np.array([[10.0, 4.0, 2.0]], dtype=np.float32),
        "content": np.array([[0.0, 1.0, 2.0]], dtype=np.float32),
    }
    seen = sparse.csr_matrix(np.array([[1, 0, 0]], dtype=np.float32))
    got = rec.blend(parts, {"cf": 0.5, "content": 0.5}, EVERY, seen)
    # best unseen: cf 4 -> [_, 1.0, 0.5]; content 2 -> [_, 0.5, 1.0]; half each
    assert got[0, 1:] == pytest.approx([0.75, 0.75])


def test_blend_of_a_user_who_has_seen_every_candidate_is_zero_not_nan():
    parts = {"cf": np.array([[3.0, 1.0, 0.0]], dtype=np.float32)}
    seen = sparse.csr_matrix(np.array([[1, 1, 0]], dtype=np.float32))
    got = rec.blend(parts, {"cf": 1.0}, np.array([True, True, False]), seen)
    assert got[0].tolist() == [0.0, 0.0, 0.0]


def test_blend_rejects_bad_weights():
    parts = {"cf": np.zeros((2, 3), dtype=np.float32)}
    with pytest.raises(ValueError, match="weight"):
        rec.blend(parts, {"cf": -0.5}, EVERY, NOTHING_SEEN)
    with pytest.raises(ValueError, match="weight"):
        rec.blend(parts, {"cf": 0.0}, EVERY, NOTHING_SEEN)
    with pytest.raises(KeyError):
        rec.blend(parts, {"nope": 1.0}, EVERY, NOTHING_SEEN)


def test_blend_with_no_candidate_raises():
    parts = {"cf": np.ones((2, 3), dtype=np.float32)}
    with pytest.raises(ValueError, match="candidate"):
        rec.blend(parts, {"cf": 1.0}, np.zeros(3, dtype=bool), NOTHING_SEEN)


def test_blend_does_not_look_up_a_part_whose_weight_is_zero():
    parts = {"content": np.array([[1.0, 2.0, 4.0]], dtype=np.float32)}
    seen = sparse.csr_matrix((1, 3), dtype=np.float32)
    got = rec.blend(parts, {"cf": 0.0, "content": 1.0}, EVERY, seen)
    assert got[0] == pytest.approx([0.25, 0.5, 1.0])


def test_top_k_skips_seen_items_and_items_outside_the_candidates():
    scores = np.array([[9.0, 8.0, 7.0, 6.0, 5.0]], dtype=np.float32)
    seen = sparse.csr_matrix(np.array([[1, 0, 0, 0, 0]], dtype=np.float32))
    candidates = np.array([True, True, False, True, True])
    idx, valid = rec.top_k(scores, seen, candidates, k=2)
    assert idx.tolist() == [[1, 3]]
    assert valid.tolist() == [[True, True]]
    assert scores[0, 0] == 9.0  # caller's array untouched


def test_top_k_breaks_ties_by_item_order():
    scores = np.array([[1.0, 3.0, 3.0, 3.0]], dtype=np.float32)
    seen = sparse.csr_matrix((1, 4), dtype=np.float32)
    idx, _ = rec.top_k(scores, seen, np.ones(4, dtype=bool), k=2)
    assert idx.tolist() == [[1, 2]]


def test_top_k_marks_slots_it_could_not_fill():
    scores = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    seen = sparse.csr_matrix(np.array([[0, 1, 0]], dtype=np.float32))
    idx, valid = rec.top_k(scores, seen, np.array([False, True, True]), k=3)
    assert idx[0, 0] == 2
    assert valid.tolist() == [[True, False, False]]


def test_top_k_zero_score_slot_is_not_a_recommendation():
    """A zero score is no evidence; filling the slot with the lowest-index film is arbitrary."""
    scores = np.array([[0.0, 2.0, 0.0, 1.0]], dtype=np.float32)
    seen = sparse.csr_matrix((1, 4), dtype=np.float32)
    idx, valid = rec.top_k(scores, seen, np.ones(4, dtype=bool), k=4)
    assert idx[0, :2].tolist() == [1, 3]
    assert valid.tolist() == [[True, True, False, False]]


def test_top_k_ties_go_to_the_lower_index_on_a_long_list():
    scores = np.tile(np.array([1.0, 2.0], dtype=np.float32), 30)[None, :]  # 30 films tie on top
    seen = sparse.csr_matrix((1, 60), dtype=np.float32)
    idx, _ = rec.top_k(scores, seen, np.ones(60, dtype=bool), k=5)
    assert idx.tolist() == [[1, 3, 5, 7, 9]]


def test_similar_items_ties_go_to_the_lower_index_on_a_long_list():
    x = sparse.csr_matrix(np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (60, 1)))
    got = rec.similar_items(x, 0, np.ones(60, dtype=bool), k=5)
    assert [i for i, _ in got] == [1, 2, 3, 4, 5]


def test_similar_items_ranks_within_candidates_and_leaves_out_the_seed():
    x = sparse.csr_matrix(
        np.array([[1, 0], [0.8, 0.6], [0.6, 0.8], [0, 1], [1, 0]], dtype=np.float32)
    )
    candidates = np.array([True, False, True, True, True])
    got = rec.similar_items(x, 0, candidates, k=3)
    assert [i for i, _ in got] == [4, 2]
    assert got[0][1] == pytest.approx(1.0)
    assert got[1][1] == pytest.approx(0.6)
