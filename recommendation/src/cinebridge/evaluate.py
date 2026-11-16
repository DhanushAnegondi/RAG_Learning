"""Offline evaluation on a time split: learn from the past, score on what users liked later."""

from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy import sparse

from cinebridge.recommend import blend, top_k

Scorer = Callable[[sparse.csr_matrix], np.ndarray]
Slice = tuple[np.ndarray, np.ndarray | None]  # (candidate items, users allowed or None)


def split_by_time(ratings: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train = rated strictly before cutoff; test = rated at or after it."""
    before = ratings["rated_at"] < cutoff
    return ratings[before], ratings[~before]


def window(ratings: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Ratings with start <= rated_at < end."""
    return ratings[(ratings["rated_at"] >= start) & (ratings["rated_at"] < end)]


def _matrix(users: pd.Index, items: pd.Index, df: pd.DataFrame) -> sparse.csr_matrix:
    data = np.ones(len(df), dtype=np.float32)
    coords = (users.get_indexer(df["user_id"]), items.get_indexer(df["movie_id"]))
    out = sparse.csr_matrix((data, coords), shape=(len(users), len(items)), dtype=np.float32)
    out.data[:] = 1.0  # a repeated (user, item) pair is still one
    return out


def _pair_key(df: pd.DataFrame) -> np.ndarray:
    """One int64 per (user, film) pair; ids are below 2**31."""
    return df["user_id"].to_numpy(np.int64) * (1 << 32) + df["movie_id"].to_numpy(np.int64)


def user_matrices(
    train: pd.DataFrame, test: pd.DataFrame, item_ids: list[int], like: float, min_profile: int
) -> tuple[np.ndarray, sparse.csr_matrix, sparse.csr_matrix, sparse.csr_matrix]:
    """Users worth testing, and their three item sets as users x items 0/1 matrices.

    profile  = items liked in train (what the recommender is told)
    seen     = every item rated in train (never recommended)
    relevant = items liked in test and not rated in train (what counts as a hit)
    A user needs min_profile liked train items and at least one relevant item.
    """
    items = pd.Index(item_ids)
    train = train[train["movie_id"].isin(items)]
    test = test[test["movie_id"].isin(items)]
    liked = train[train["rating"] >= like]
    later = test[test["rating"] >= like]
    later = later[~np.isin(_pair_key(later), _pair_key(train))]
    likes_per_user = liked.groupby("user_id").size()
    enough = likes_per_user.index[likes_per_user >= min_profile]
    users = pd.Index(np.sort(np.intersect1d(enough, later["user_id"].unique())))
    keep = lambda df: df[df["user_id"].isin(users)]  # noqa: E731
    return (
        users.to_numpy(),
        _matrix(users, items, keep(liked)),
        _matrix(users, items, keep(train)),
        _matrix(users, items, keep(later)),
    )


def rank_metrics(
    recs: np.ndarray, valid: np.ndarray, relevant: sparse.csr_matrix
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-user Recall@K, NDCG@K and hit (1 if any recommended item is relevant).

    recall = hits / relevant items. NDCG discounts a hit at rank r by 1/log2(r + 1) and divides
    by the best possible value for that user (min(K, relevant) hits at the top).
    """
    k = recs.shape[1]
    rel = relevant.toarray() > 0
    hits = np.take_along_axis(rel, recs, axis=1) & valid
    n_rel = rel.sum(axis=1)
    discount = 1.0 / np.log2(np.arange(2, k + 2))
    ideal = np.concatenate([[0.0], np.cumsum(discount)])[np.minimum(n_rel, k)]
    safe = np.maximum(n_rel, 1)
    recall = hits.sum(axis=1) / safe
    ndcg = np.divide((hits * discount).sum(axis=1), ideal, out=np.zeros(len(recs)), where=ideal > 0)
    return recall, ndcg, hits.any(axis=1).astype(float)


def _in_shelf(relevant: sparse.csr_matrix, candidates: np.ndarray) -> sparse.csr_matrix:
    """Relevant items that are also candidates."""
    return sparse.csr_matrix(relevant.multiply(candidates.astype(np.float32)[None, :]))


def evaluate(
    parts: dict[str, Scorer],
    methods: dict[str, dict[str, float]],
    profile: sparse.csr_matrix,
    seen: sparse.csr_matrix,
    relevant: sparse.csr_matrix,
    slices: dict[str, Slice],
    k: int,
    batch: int = 256,
) -> pd.DataFrame:
    """Mean Recall@K / NDCG@K / hit rate per slice and method.

    parts are the raw scorers (popularity, content, ...). A method is a set of weights over
    them: {"content": 1.0} is content alone, {"item_item": 0.75, "content": 0.25} a blend.
    A slice limits which items may be recommended and which hits count (the same limit for
    every method, baselines included), and optionally which users take part. Within a slice,
    only users with at least one relevant item in it are scored.
    """
    n_users = profile.shape[0]
    plans = {}
    for name, (candidates, allowed) in slices.items():
        rel = _in_shelf(relevant, candidates)
        takes_part = np.asarray(rel.sum(axis=1)).ravel() > 0
        if allowed is not None:
            takes_part &= allowed
        plans[name] = (candidates, rel, takes_part)
    anyone = np.any([p[2] for p in plans.values()], axis=0)
    used = {name for weights in methods.values() for name, w in weights.items() if w > 0}
    totals = {(s, m): np.zeros(3) for s in slices for m in methods}
    for start in range(0, n_users, batch):
        active = start + np.flatnonzero(anyone[start : start + batch])
        if not len(active):
            continue
        scores = {name: parts[name](profile[active]) for name in used}
        for name, (candidates, rel, takes_part) in plans.items():
            part = np.flatnonzero(takes_part[active])
            if not len(part):
                continue
            sub = {n: s[part] for n, s in scores.items()}
            for method, weights in methods.items():
                seen_now = seen[active[part]]
                blended = blend(sub, weights, candidates, seen_now)
                recs, valid = top_k(blended, seen_now, candidates, k)
                metrics = rank_metrics(recs, valid, rel[active[part]])
                totals[(name, method)] += [m.sum() for m in metrics]
    out = []
    for name, (_, _, takes_part) in plans.items():
        n = int(takes_part.sum())
        for method in methods:
            recall, ndcg, hit = totals[(name, method)] / n if n else [np.nan] * 3
            out.append(
                {
                    "slice": name,
                    "method": method,
                    "users": n,
                    "recall_at_k": recall,
                    "ndcg_at_k": ndcg,
                    "hit_rate": hit,
                }
            )
    return pd.DataFrame(out)


def choose_weights(
    parts: dict[str, Scorer],
    grid: list[dict[str, float]],
    profile: sparse.csr_matrix,
    seen: sparse.csr_matrix,
    relevant: sparse.csr_matrix,
    candidates: np.ndarray,
    k: int,
    batch: int = 256,
) -> tuple[dict[str, float], pd.DataFrame]:
    """Pick the blend weights with the best Recall@K among `candidates` on these users.

    Call this with validation data only; the test window must never reach it. A tie goes to
    the entry that comes first in `grid`. Returns (weights, one table row per grid entry).
    """
    rel = _in_shelf(relevant, candidates)
    takes_part = np.flatnonzero(np.asarray(rel.sum(axis=1)).ravel() > 0)
    used = {name for weights in grid for name, w in weights.items() if w > 0}
    totals = np.zeros((len(grid), 2))
    for start in range(0, len(takes_part), batch):
        rows = takes_part[start : start + batch]
        scores = {name: parts[name](profile[rows]) for name in used}
        for i, weights in enumerate(grid):
            blended = blend(scores, weights, candidates, seen[rows])
            recs, valid = top_k(blended, seen[rows], candidates, k)
            recall, ndcg, _ = rank_metrics(recs, valid, rel[rows])
            totals[i] += [recall.sum(), ndcg.sum()]
    n = len(takes_part)
    table = pd.DataFrame(grid)
    table["users"] = n
    table["recall_at_k"] = totals[:, 0] / max(n, 1)
    table["ndcg_at_k"] = totals[:, 1] / max(n, 1)
    best = int(np.flatnonzero(table["recall_at_k"] >= table["recall_at_k"].max() - 1e-12)[0])
    return dict(grid[best]), table
