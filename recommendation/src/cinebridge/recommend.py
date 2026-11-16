"""Scoring: popularity, content ("films like the ones you liked"), item-item, and a blend.

Matrices are users x items or items x items; column j is always the j-th film of the cleaned
film table. Scores are dense float32 arrays, one row per user.
"""

import numpy as np
from scipy import sparse
from sklearn.preprocessing import normalize


def popularity_scores(likes: sparse.csr_matrix) -> np.ndarray:
    """Number of users who liked each item."""
    return np.asarray(likes.sum(axis=0)).ravel().astype(np.float32)


def item_neighbors(
    likes: sparse.csr_matrix, top_n: int = 50, shrink: float = 0.0, block: int = 256
) -> sparse.csr_matrix:
    """Item-item similarity from shared likes, keeping the top_n neighbours of each item.

        sim(i, j) = users who liked both / (sqrt(likes_i * likes_j) + shrink)

    shrink > 0 pulls down pairs backed by very few users (one shared fan of two films with one
    like each would otherwise score a perfect 1.0).
    """
    likes = sparse.csr_matrix(likes, dtype=np.float32)
    n_items = likes.shape[1]
    counts = np.asarray(likes.sum(axis=0)).ravel().astype(np.float32)
    by_item = likes.T.tocsr()
    rows, cols, vals = [], [], []
    for start in range(0, n_items, block):
        stop = min(start + block, n_items)
        both = (by_item[start:stop] @ likes).toarray()
        denom = np.sqrt(np.outer(counts[start:stop], counts)) + np.float32(shrink)
        sim = np.divide(both, denom, out=np.zeros_like(both), where=denom > 0)
        sim[np.arange(stop - start), np.arange(start, stop)] = 0.0
        if top_n < n_items:
            keep = np.argpartition(-sim, top_n - 1, axis=1)[:, :top_n]
        else:
            keep = np.tile(np.arange(n_items), (stop - start, 1))
        kept = np.take_along_axis(sim, keep, axis=1)
        r, c = np.nonzero(kept > 0)
        rows.append(r + start)
        cols.append(keep[r, c])
        vals.append(kept[r, c])
    return sparse.csr_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n_items, n_items),
        dtype=np.float32,
    )


def cf_scores(profile: sparse.csr_matrix, neighbors: sparse.csr_matrix) -> np.ndarray:
    """Sum of similarity between each item and the items the user liked."""
    return np.asarray((profile @ neighbors).toarray(), dtype=np.float32)


def content_scores(profile: sparse.csr_matrix, items: sparse.csr_matrix) -> np.ndarray:
    """Cosine between each item vector and the mean vector of the items the user liked."""
    taste = normalize(profile @ items)
    # sparse items x dense taste: a sparse x sparse product here is near-dense and ~50x slower
    return np.ascontiguousarray((items @ taste.T.toarray()).T, dtype=np.float32)


def blend(
    parts: dict[str, np.ndarray],
    weights: dict[str, float],
    candidates: np.ndarray,
    seen: sparse.csr_matrix,
) -> np.ndarray:
    """Weighted sum of score parts, each first scaled so that a user's best *unseen candidate* is 1.

    Scaling inside the candidate set matters: on a small shelf (say, Telugu films only) a
    part's scores can all be tiny next to its best score over the whole catalogue, and scaling
    by that would mute the part. Films the user has already rated can never be recommended, so
    they must not set the scale either (a user's own favourite often scores far above the rest).
    A part that is all zero for a user adds nothing for them. Scores are never negative.
    """
    if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError(f"blend weights must be non-negative and not all zero, got {weights}")
    if not candidates.any():
        raise ValueError("blend needs at least one candidate film")
    pool = np.flatnonzero(candidates)
    unseen = sparse.csr_matrix(seen)[:, pool].toarray() == 0
    total = None
    for name, weight in weights.items():
        if weight == 0:
            continue
        scores = parts[name]
        top = np.where(unseen, scores[:, pool], 0.0).max(axis=1, keepdims=True)
        scaled = np.divide(scores, top, out=np.zeros_like(scores, dtype=np.float32), where=top > 0)
        total = weight * scaled if total is None else total + weight * scaled
    return total


def top_k(
    scores: np.ndarray, seen: sparse.csr_matrix, candidates: np.ndarray, k: int
) -> tuple[np.ndarray, np.ndarray]:
    """Best k item indices per user among `candidates`, never an item the user has rated.

    Ties go to the lower item index. Returns (indices, valid); valid is False for a slot that
    could not be filled (fewer than k unseen candidates) or whose score is not above zero (zero
    means no evidence, and filling it with the lowest-index film would be arbitrary). Such a
    slot must not count as a recommendation.
    """
    cand = np.flatnonzero(candidates)
    sub = np.array(scores[:, cand], dtype=np.float32, copy=True)
    sub[sparse.csr_matrix(seen)[:, cand].toarray() > 0] = -np.inf
    order = np.argsort(-sub, axis=1, kind="stable")[:, :k]
    valid = np.take_along_axis(sub, order, axis=1) > 0
    picked = cand[order]
    short = k - picked.shape[1]  # fewer candidates than k: pad so the shape is always (users, k)
    if short > 0:
        picked = np.pad(picked, ((0, 0), (0, short)))
        valid = np.pad(valid, ((0, 0), (0, short)))
    return picked, valid


def similar_items(
    items: sparse.csr_matrix, index: int, candidates: np.ndarray, k: int
) -> list[tuple[int, float]]:
    """The k candidates most similar to one film, as (item index, cosine); zero matches left out."""
    sims = np.asarray((items @ items[index].T).toarray()).ravel()
    sims[index] = 0.0
    sims[~candidates] = 0.0
    order = np.argsort(-sims, kind="stable")[:k]
    return [(int(i), float(sims[i])) for i in order if sims[i] > 0]
