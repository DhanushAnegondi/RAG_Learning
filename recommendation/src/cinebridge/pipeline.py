"""End-to-end run: land -> DuckDB raw/staging -> clean (fill, never drop) -> models -> results.

Everything the results page shows is written here, under results/<sprint>/, from measured
tables. Printed output stays ASCII (Windows console); files are UTF-8 and keep Telugu script.
"""

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy import sparse

from cinebridge import clean, evaluate, recommend, warehouse
from cinebridge.config import Settings
from cinebridge.features import build_item_matrix, split_list
from cinebridge.ingest import download, extract_movielens

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LANGUAGE_NAME = {"en": "English", "te": "Telugu"}
# Seeds for the bridge table, by IMDb id so a retitled film is still found.
BRIDGE_SEEDS = (
    "tt1375666",  # Inception
    "tt0468569",  # The Dark Knight
    "tt0120338",  # Titanic
    "tt0172495",  # Gladiator
    "tt0332280",  # The Notebook
    "tt0107290",  # Jurassic Park
    "tt8178634",  # RRR
    "tt2631186",  # Baahubali: The Beginning
    "tt20850406",  # Sita Ramam
    "tt2258337",  # Eega
)
TABLES = (
    "raw_movies",
    "raw_ratings",
    "raw_links",
    "stg_movies",
    "stg_ratings",
    "mart_movies_clean",
    "mart_missing_audit",
    "mart_scope_audit",
    "mart_rating_coverage",
    "mart_split",
    "mart_model_ratings",
    "mart_like_counts",
)
METHOD_LABEL = {
    "popularity": "most popular (baseline)",
    "content": "content: films like your likes",
    "item_item": "item-item: liked by the same people",
    "hybrid": "hybrid: blend weighted on validation",
}
# A method must lead the runner-up by at least this much Recall@K (and also lead on NDCG@K)
# before the page calls it best; anything closer is reported as no clear winner.
BEST_RECALL_MARGIN = 0.005
SLICE_LABEL = {
    "all": "all films",
    "telugu": "Telugu films only",
    "telugu_first_time": "Telugu films, users with no Telugu film in their history",
}


def say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"), flush=True)


def query(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def fit_collaborative(
    ratings: pd.DataFrame, before: pd.Timestamp, item_ids: list[int], settings: Settings
) -> sparse.csr_matrix:
    """Item-item neighbours from the sampled users' likes before `before`."""
    rows = ratings[
        ratings["is_cf_user"]
        & (ratings["rated_at"] < before)
        & (ratings["rating"] >= settings.like_rating)
    ]
    users, items = pd.Index(rows["user_id"].unique()), pd.Index(item_ids)
    likes = sparse.csr_matrix(
        (
            np.ones(len(rows), dtype=np.float32),
            (users.get_indexer(rows["user_id"]), items.get_indexer(rows["movie_id"])),
        ),
        shape=(len(users), len(items)),
    )
    likes.data[:] = 1.0  # a repeated like of one film is still one like
    return recommend.item_neighbors(likes, top_n=settings.cf_neighbors, shrink=settings.cf_shrink)


def popularity_vector(counts: pd.DataFrame, item_ids: list[int], column: str) -> np.ndarray:
    """Likes per film from the like-count mart, in film order; a film with no row has 0."""
    by_film = counts.set_index("movie_id")[column]
    return by_film.reindex(item_ids).fillna(0).to_numpy(dtype=np.float32)


def released_before(release_dates: pd.Series, end: pd.Timestamp) -> np.ndarray:
    """True for films that could still be hits in a window ending at `end`: release date unknown
    (kept), or before `end`. A film released on or after `end` has no rating inside the window.
    A film released inside the window stays: it is a real cold-start target."""
    dates = pd.to_datetime(release_dates, errors="coerce")
    return (dates.isna() | (dates < end)).to_numpy()


def eval_windows(
    ratings: pd.DataFrame,
    val_start: pd.Timestamp,
    test_start: pd.Timestamp,
    window_end: pd.Timestamp,
    item_ids: list[int],
    release_dates: pd.Series,
    like_counts: pd.DataFrame,
    settings: Settings,
) -> dict[str, dict]:
    """Everything each evaluation window is allowed to know, and nothing from after its cutoff.

    validation: fitted on ratings before val_start, scored on likes in [val_start, test_start)
    test:       fitted on ratings before test_start, scored on likes from test_start on
    Each window returns its scored users, the profile / seen / relevant matrices, the
    candidate mask (films released before the window ends), how many films the mask left out,
    the item-item neighbours and the popularity vector (all users' likes before the cutoff).
    """
    like, min_profile = settings.like_rating, settings.min_profile_likes
    eval_ratings = ratings[ratings["is_eval_user"]]
    fit_v, later_v = evaluate.split_by_time(eval_ratings, val_start)
    val = evaluate.user_matrices(
        fit_v, evaluate.window(later_v, val_start, test_start), item_ids, like, min_profile
    )
    train, test = evaluate.split_by_time(eval_ratings, test_start)
    final = evaluate.user_matrices(train, test, item_ids, like, min_profile)
    out = {}
    for name, (users, profile, seen, relevant), cutoff, end, column in (
        ("validation", val, val_start, test_start, "likes_before_val"),
        ("test", final, test_start, window_end, "likes_before_test"),
    ):
        candidates = released_before(release_dates, end)
        out[name] = {
            "users": users,
            "profile": profile,
            "seen": seen,
            "relevant": relevant,
            "candidates": candidates,
            "excluded": int((~candidates).sum()),
            "neighbors": fit_collaborative(ratings, cutoff, item_ids, settings),
            "popularity": popularity_vector(like_counts, item_ids, column),
        }
    return out


def score_parts(
    items: sparse.csr_matrix, neighbors: sparse.csr_matrix, popularity: np.ndarray
) -> dict:
    """The three raw scorers every method is a weighting of."""
    return {
        "popularity": lambda p: np.tile(popularity, (p.shape[0], 1)),
        "content": lambda p: recommend.content_scores(p, items),
        "item_item": lambda p: recommend.cf_scores(p, neighbors),
    }


def weight_grid(step: float) -> list[dict[str, float]]:
    """Every (content, item_item, popularity) split of 1.0 in multiples of step.

    Ordered content-heavy first, so a tie on validation goes to the blend that leans most on
    content (the only part that can reach films nobody has rated).
    """
    n = round(1 / step)
    return [
        {"content": c / n, "item_item": i / n, "popularity": (n - c - i) / n}
        for c in range(n, -1, -1)
        for i in range(n - c, -1, -1)
    ]


SOLO = {name: {name: 1.0} for name in ("popularity", "content", "item_item")}


def choose_shelf_weights(
    windows: dict[str, dict], items: sparse.csr_matrix, telugu: np.ndarray, settings: Settings
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, bool]:
    """Blend weights for the all-films shelf and the Telugu shelf, from the VALIDATION window only.

    A shelf with fewer than settings.min_validation_users validation users has too little to
    choose from: the Telugu shelf then borrows the all-films weights (the third value says so).
    Returns ({shelf: weights used}, one table row per blend tried per shelf, fell_back).
    """
    v = windows["validation"]
    parts = score_parts(items, v["neighbors"], v["popularity"])
    grid = weight_grid(settings.weight_step)
    chosen = {}
    tables = []
    for shelf, candidates in (
        ("all films", v["candidates"]),
        ("Telugu shelf", v["candidates"] & telugu),
    ):
        weights, table = evaluate.choose_weights(
            parts, grid, v["profile"], v["seen"], v["relevant"], candidates, settings.k
        )
        chosen[shelf] = weights
        tables.append(table.assign(shelf=shelf))
    table = pd.concat(tables)
    fell_back = int(tables[1]["users"].iloc[0]) < settings.min_validation_users
    if fell_back:
        chosen["Telugu shelf"] = chosen["all films"]
    return chosen, table, fell_back


def score_test(
    windows: dict[str, dict],
    items: sparse.csr_matrix,
    weights: dict[str, dict[str, float]],
    telugu: np.ndarray,
    k: int,
) -> pd.DataFrame:
    """Recall / NDCG / hit rate on the TEST window: every method on the same users and the same
    candidates, overall and on the Telugu shelf, and for Telugu newcomers (no Telugu film in
    their history)."""
    t = windows["test"]
    parts = score_parts(items, t["neighbors"], t["popularity"])
    no_telugu_history = np.asarray(t["seen"][:, np.flatnonzero(telugu)].sum(axis=1)).ravel() == 0
    everything = t["candidates"]
    shelf = t["candidates"] & telugu
    matrices = (t["profile"], t["seen"], t["relevant"])
    overall = evaluate.evaluate(
        parts, {**SOLO, "hybrid": weights["all films"]}, *matrices, {"all": (everything, None)}, k
    )
    on_shelf = evaluate.evaluate(
        parts,
        {**SOLO, "hybrid": weights["Telugu shelf"]},
        *matrices,
        {"telugu": (shelf, None), "telugu_first_time": (shelf, no_telugu_history)},
        k,
    )
    return pd.concat([overall, on_shelf], ignore_index=True)


def bridge_table(films: pd.DataFrame, items: sparse.csr_matrix, k: int = 5) -> pd.DataFrame:
    """For each seed film, the k most similar films in the other language."""
    language = films["language"].to_numpy()
    position = {imdb: i for i, imdb in enumerate(films["imdb_id"])}
    rows = []
    for imdb in BRIDGE_SEEDS:
        if imdb not in position:
            continue
        seed = position[imdb]
        other = "te" if language[seed] == "en" else "en"
        seed_genres = set(split_list(films["genres"].iloc[seed]))
        listed: set[str] = set()
        for j, sim in recommend.similar_items(items, seed, language == other, 4 * k):
            pick = films.iloc[j]
            if pick["title"] in listed or len(listed) == k:
                continue  # the source lists some films twice under different ids
            listed.add(pick["title"])
            rank = len(listed)
            rows.append(
                {
                    "if_you_liked": films["title"].iloc[seed],
                    "seed_language": LANGUAGE_NAME[language[seed]],
                    "rank": rank,
                    "try_this": pick["title"],
                    "original_title": pick["original_title"],
                    "language": LANGUAGE_NAME[other],
                    "year": int(pick["release_year"]),
                    "similarity": round(sim, 3),
                    "shared_genres": ", ".join(
                        sorted(seed_genres & set(split_list(pick["genres"])))
                    ),
                    "score": round(float(pick["score"]), 2),
                }
            )
    return pd.DataFrame(rows)


def like_spread(
    relevant: sparse.csr_matrix, shelf: np.ndarray, films: pd.DataFrame, top: int = 10
) -> pd.DataFrame:
    """Which shelf films the test users went on to like, most-liked first.

    If a handful of films hold nearly all the likes, "recommend the most popular" is close to
    unbeatable on that shelf and the test says little about personalisation.
    """
    likes = (
        np.asarray(relevant.sum(axis=0), dtype=np.float64).ravel() * shelf
    )  # float32 rounds badly
    order = np.argsort(-likes, kind="stable")
    order = order[likes[order] > 0]
    total = likes.sum()
    rows = [
        {
            "title": films["title"].iloc[i],
            "original_title": films["original_title"].iloc[i],
            "year": int(films["release_year"].iloc[i]),
            "test_likes": int(likes[i]),
            "share_pct": round(100.0 * likes[i] / total, 1),
            "cumulative_pct": round(100.0 * likes[order[: n + 1]].sum() / total, 1),
            "films_liked_in_total": len(order),
        }
        for n, i in enumerate(order[:top])
    ]
    columns = [
        "title",
        "original_title",
        "year",
        "test_likes",
        "share_pct",
        "cumulative_pct",
        "films_liked_in_total",
    ]
    return pd.DataFrame(rows, columns=columns)


def fill_examples(cleaned: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    """Telugu films with the most gaps: what was missing and what it was filled with."""
    flags = [
        f"{c}_filled" for c in ("genres", "runtime_min", "overview", "keywords", "release_year")
    ]
    telugu = cleaned[cleaned["language"] == "te"].copy()
    telugu["gaps"] = telugu[flags].sum(axis=1)
    worst = telugu.sort_values(["gaps", "imdb_votes", "movie_id"], ascending=[False, False, True])
    rows = []
    for _, film in worst.head(n).iterrows():
        rows.append(
            {
                "title": film["title"],
                "original_title": film["original_title"],
                "gaps_filled": int(film["gaps"]),
                "genres": film["genres"] + (" (filled)" if film["genres_filled"] else ""),
                "runtime_min": f"{film['runtime_min']}"
                + (" (filled)" if film["runtime_min_filled"] else ""),
                "release_year": f"{film['release_year']}"
                + (" (filled)" if film["release_year_filled"] else ""),
                "keywords": film["keywords"] + (" (filled)" if film["keywords_filled"] else ""),
                "overview": film["overview"][:90]
                + (" (filled)" if film["overview_filled"] else ""),
            }
        )
    return pd.DataFrame(rows)


def chart_missing(audit: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    for ax, language in zip(axes, ("te", "en"), strict=True):
        part = audit[audit["language"] == language].sort_values("missing_before_pct")
        ax.barh(part["column_name"], part["missing_before_pct"], color="#c2410c", label="before")
        ax.barh(
            part["column_name"],
            100.0 * part["missing_after"] / part["total_rows"],
            color="#0e7490",
            label="after",
        )
        for y, pct in enumerate(part["missing_before_pct"]):
            ax.text(pct + 1, y, f"{pct:.1f}%", va="center", fontsize=8)
        ax.set_title(f"{LANGUAGE_NAME[language]}: {int(part['total_rows'].iloc[0]):,} films")
        ax.set_xlabel("% of films missing the field")
        ax.set_xlim(0, 100)
    axes[0].legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_eval(result: pd.DataFrame, k: int, path: Path) -> None:
    names = list(result["slice"].unique())
    fig, axes = plt.subplots(1, len(names), figsize=(4.2 * len(names), 3.8))
    colors = {
        "popularity": "#93a4b7",
        "content": "#0e7490",
        "item_item": "#0b6bcb",
        "hybrid": "#c2410c",
    }
    for ax, name in zip(np.atleast_1d(axes), names, strict=True):
        part = result[result["slice"] == name]
        ax.bar(part["method"], part["recall_at_k"], color=[colors[m] for m in part["method"]])
        for x, value in enumerate(part["recall_at_k"]):
            ax.text(x, value, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
        ax.set_title(f"{SLICE_LABEL[name]}\n{int(part['users'].iloc[0]):,} users", fontsize=9)
        ax.set_ylabel(f"Recall@{k}")
        ax.tick_params(axis="x", labelsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_fill_quality(quality: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4))
    for ax, col in zip(axes, clean.MASKABLE, strict=True):
        part = quality[quality["column_name"] == col]
        x = np.arange(len(part))
        ax.bar(x - 0.2, part["naive_error"], 0.4, color="#93a4b7", label="naive fill")
        ax.bar(x + 0.2, part["fill_error"], 0.4, color="#0e7490", label="this pipeline")
        ax.set_xticks(x, [LANGUAGE_NAME.get(v, v) for v in part["language"]])
        ax.set_title(f"{col}\n{part['metric'].iloc[0]} (lower is better)", fontsize=9)
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _verdict(part: pd.DataFrame) -> str:
    """Name a best method only when one leads on Recall and on NDCG and its recall lead over the
    runner-up is at least the margin; otherwise say there is no clear winner.

    The margin is BEST_RECALL_MARGIN or 1/sqrt(users), whichever is larger: per-user recall lies
    in [0, 1], so 1/sqrt(users) is about two standard errors of a mean at its widest. It is a
    rough guard against calling a winner on a few users, not a significance test.
    """
    users = int(part["users"].iloc[0])
    margin = round(max(BEST_RECALL_MARGIN, 1 / np.sqrt(users)), 6)
    by_recall = part["recall_at_k"].sort_values(ascending=False, kind="stable")
    best = by_recall.index[0]
    lead = round(float(by_recall.iloc[0] - by_recall.iloc[1]), 6) if len(by_recall) > 1 else 0.0
    if best == part["ndcg_at_k"].idxmax() and lead >= margin:
        return f"Best: {best} (best Recall and NDCG; recall lead {lead:.3f} over {by_recall.index[1]})."
    return (
        "There is no clear winner (a method must lead on both Recall and NDCG and by at least"
        f" {margin:.3f} Recall for {users:,} users)."
    )


def findings(
    scope: pd.DataFrame,
    audit: pd.DataFrame,
    quality: pd.DataFrame,
    coverage: pd.DataFrame,
    result: pd.DataFrame,
    weights: dict[str, dict[str, float]],
    spread: pd.DataFrame,
    k: int,
    *,
    staged_rows: int,
    cleaned_rows: int,
    excluded: dict[str, int],
    val_users: dict[str, int],
    weight_fallback: bool,
    min_val_users: int,
) -> list[str]:
    """Plain sentences for the top of the page, each built from a measured table or count."""
    out = []
    kept = scope.set_index("language")["kept"]
    out.append(
        f"Catalogue: {int(kept['te']):,} Telugu and {int(kept['en']):,} English films"
        f" ({int(scope['landed_rows'].sum()):,} rows landed; {int(scope['duplicate_rows'].sum()):,}"
        " rows are extra copies of an id (one copy of each id is kept),"
        f" {int(scope['adult_titles'].sum()):,} adult titles and"
        f" {int(scope['below_vote_floor'].sum()):,} English films under the vote floor are left out"
        " of the project scope and counted in the scope table)."
    )
    filled = int(audit["missing_before"].sum())
    out.append(
        f"Cleaning filled {filled:,} missing values and dropped {staged_rows - cleaned_rows} rows;"
        f" {int(audit['missing_after'].sum())} values are still missing in the filled columns."
    )
    te = audit[audit["language"] == "te"].sort_values("missing_before", ascending=False).head(4)
    out.append(
        "Telugu gaps before cleaning: "
        + "; ".join(
            f"{r.column_name} {r.missing_before:,} of {r.total_rows:,} ({r.missing_before_pct}%)"
            for r in te.itertuples()
        )
        + "."
    )
    for row in quality[quality["language"] == "te"].itertuples():
        out.append(
            f"Fill check, Telugu {row.column_name} ({row.masked_rows} real values hidden then"
            f" refilled): {row.metric} {row.fill_error:.2f} vs {row.naive_error:.2f} for the naive"
            " fill (the language median, or the language's three commonest genres)."
        )
    cov = coverage.set_index("language")
    out.append(
        f"Rating evidence: {int(cov.loc['te', 'movies_with_ratings']):,} of"
        f" {int(cov.loc['te', 'movies']):,} Telugu films have any MovieLens rating"
        f" ({int(cov.loc['te', 'ratings']):,} ratings) against"
        f" {int(cov.loc['en', 'movies_with_ratings']):,} of {int(cov.loc['en', 'movies']):,} English"
        f" films ({int(cov.loc['en', 'ratings']):,} ratings)."
    )
    out.append(
        "Films released on or after the end of a window cannot be hits, so they are left out of"
        f" every method's candidates: {excluded['validation']:,} films for validation and"
        f" {excluded['test']:,} for test (films released inside a window, and films with no"
        " release date, stay)."
    )
    for name in result["slice"].unique():
        part = result[result["slice"] == name].set_index("method")
        users = int(part["users"].iloc[0])
        if not users:
            out.append(f"{SLICE_LABEL[name]}: no test users, nothing measured.")
            continue
        recall = ", ".join(f"{m} {part.loc[m, 'recall_at_k']:.3f}" for m in part.index)
        ndcg = ", ".join(f"{m} {part.loc[m, 'ndcg_at_k']:.3f}" for m in part.index)
        out.append(
            f"{SLICE_LABEL[name]} ({users:,} test users), Recall@{k}: {recall}; NDCG@{k}: {ndcg}."
            f" {_verdict(part)}"
        )
    if len(spread):
        top3 = spread.head(3)
        out.append(
            f"Telugu test likes: the most-liked film, {spread['title'].iloc[0]}, holds"
            f" {spread['share_pct'].iloc[0]}% of them; the top {len(top3)}"
            f" ({', '.join(top3['title'])}) hold {top3['cumulative_pct'].iloc[-1]}%;"
            f" {int(spread['films_liked_in_total'].iloc[0])} distinct Telugu films were liked in"
            " the test window."
        )
    out.append(
        "Hybrid blend weights, picked on the validation window only: "
        + "; ".join(
            f"{shelf} ({val_users[shelf]:,} validation users): "
            + ", ".join(f"{part} {w}" for part, w in chosen.items())
            for shelf, chosen in weights.items()
        )
        + "."
    )
    if weight_fallback:
        out.append(
            f"The Telugu shelf has {val_users['Telugu shelf']:,} validation users, fewer than"
            f" {min_val_users}, so it uses the all-films weights."
        )
    return out


def limit_notes(
    settings: Settings,
    *,
    telugu_test_users: int,
    telugu_val_users: int,
    telugu_rated_films: int,
    telugu_films: int,
) -> list[str]:
    """The limits shown on the page. Counts come from the run; nothing is asserted that was not
    measured."""
    return [
        "MovieLens users are mostly English-language viewers, not a Telugu audience. The Telugu"
        f" rows rest on {telugu_test_users:,} Telugu test users, {telugu_val_users:,} Telugu"
        f" validation users, and {telugu_rated_films:,} of {telugu_films:,} Telugu films have any"
        " rating.",
        "One test window. Offline Recall@K is a proxy: it rewards predicting what people rated,"
        " not what they would have enjoyed if shown.",
        f"Item-item similarity is learned from a 1-in-{settings.cf_user_mod} sample of users to"
        " keep the run short; popularity counts every user.",
        "Feature weights (text 1.0, people 0.6, genres 0.6) are fixed by hand, not tuned.",
        "Filled genres, runtime and year are estimates, flagged per row. Built overviews, derived"
        " keywords, filled genres and the Unknown person placeholder are for display and are not"
        " used as similarity signals.",
        "Films released on or after a window's end are left out of that window's candidates for"
        " every method; films with no release date stay.",
        f"The English vote floor ({settings.en_min_votes:,} IMDb votes) uses vote counts from a"
        " 2024 snapshot of the metadata, applied equally to every method.",
        "The bridge table is content-only and unrated by users; treat it as examples, not proof.",
        "Metadata is a TMDB + IMDb snapshot hosted on Hugging Face; ratings end in October 2023.",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sprint", default="sprint-01")
    parser.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    parser.add_argument("--en-min-votes", type=int, default=Settings.en_min_votes)
    parser.add_argument("--cf-user-mod", type=int, default=Settings.cf_user_mod)
    args = parser.parse_args(argv)
    settings = replace(Settings(), en_min_votes=args.en_min_votes, cf_user_mod=args.cf_user_mod)
    out = ROOT / "results" / args.sprint
    for sub in ("metrics", "charts", "tables", "run"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    started = time.time()

    raw = ROOT / "data" / "raw"
    movies_file = download(settings.movies_url, raw / "tmdb_imdb_movies.parquet")
    files = extract_movielens(
        download(settings.movielens_url, raw / "ml-32m.zip"), raw / "movielens"
    )
    say(f"[1/7] landed {movies_file.name} ({movies_file.stat().st_size:,} bytes), ml-32m.zip")

    con = warehouse.connect(args.db)
    n_movies = warehouse.load_movies(con, movies_file)
    n_ratings = warehouse.load_ratings(con, files["ratings"], files["links"])
    warehouse.build_staging(con, settings.en_min_votes)
    staged = query(con, "select * from stg_movies order by movie_id")
    say(
        f"[2/7] raw_movies {n_movies:,} rows, raw_ratings {n_ratings:,} rows, stg_movies {len(staged):,} rows"
    )

    cleaned = clean.clean_movies(staged, k=settings.genre_neighbors)
    warehouse.write_clean(con, cleaned)
    warehouse.build_marts(
        con,
        test_months=settings.test_months,
        val_months=settings.val_months,
        cf_user_mod=settings.cf_user_mod,
        like_rating=settings.like_rating,
    )
    audit = query(
        con,
        "select * from mart_missing_audit order by language desc, missing_before desc, column_name",
    )
    scope = query(con, "select * from mart_scope_audit order by language desc")
    coverage = query(con, "select * from mart_rating_coverage order by language desc")
    say(
        f"[3/7] cleaned {len(cleaned):,} rows (staged {len(staged):,}); filled"
        f" {int(audit['missing_before'].sum()):,} values; still missing {int(audit['missing_after'].sum())}"
    )

    quality = clean.masked_fill_check(cleaned, seed=settings.seed, k=settings.genre_neighbors)
    say("[4/7] fill check done (10% of observed runtime, year, genres hidden and refilled)")

    split = query(con, "select * from mart_split").iloc[0]
    test_start, val_start = pd.Timestamp(split["test_start"]), pd.Timestamp(split["val_start"])
    ratings = query(
        con,
        "select user_id::integer as user_id, movie_id::integer as movie_id, rating::float as rating,"
        " rated_at, is_cf_user, is_eval_user from mart_model_ratings",
    )
    item_ids = cleaned["movie_id"].tolist()
    items = build_item_matrix(cleaned)
    say(
        f"[5/7] model ratings {len(ratings):,}; item matrix {items.shape[0]:,} x {items.shape[1]:,};"
        f" validation from {val_start.date()}, test from {test_start.date()}"
    )

    like_counts = query(con, "select * from mart_like_counts")
    window_end = pd.Timestamp(split["last_rating"]).normalize() + pd.Timedelta(days=1)
    windows = eval_windows(
        ratings,
        val_start,
        test_start,
        window_end,
        item_ids,
        cleaned["release_date"],
        like_counts,
        settings,
    )
    say(f"      windows built ({time.time() - started:.0f}s)")
    telugu = (cleaned["language"] == "te").to_numpy()
    weights, weight_table, fell_back = choose_shelf_weights(windows, items, telugu, settings)
    val_users = weight_table.groupby("shelf")["users"].first().astype(int).to_dict()
    say(
        f"[6/7] validation users {len(windows['validation']['users']):,}"
        f" (all films {val_users['all films']:,}, Telugu shelf {val_users['Telugu shelf']:,});"
        f" weights all {weights['all films']}; telugu {weights['Telugu shelf']}"
        f"{' (fell back to all films)' if fell_back else ''} ({time.time() - started:.0f}s)"
    )
    excluded = {name: windows[name]["excluded"] for name in windows}
    say(f"      films left out of the candidates (released after the window ends): {excluded}")

    k = settings.k
    result = score_test(windows, items, weights, telugu, k)
    say(f"[7/7] test users {len(windows['test']['users']):,}")
    spread = like_spread(windows["test"]["relevant"], telugu, cleaned)
    for row in result.itertuples():
        say(
            f"      {row.slice:18s} {row.method:10s} users {row.users:6d}  recall@{k} {row.recall_at_k:.4f}  ndcg@{k} {row.ndcg_at_k:.4f}"
        )

    metrics = out / "metrics"
    shown = result.assign(
        method=result["method"].map(METHOD_LABEL), slice=result["slice"].map(SLICE_LABEL)
    )
    shown = shown.rename(
        columns={"recall_at_k": f"recall_at_{k}", "ndcg_at_k": f"ndcg_at_{k}"}
    ).round(4)
    shown.to_csv(metrics / "01_eval_by_slice.csv", index=False, encoding="utf-8")
    bridge_table(cleaned, items).to_csv(
        metrics / "02_bridge_examples.csv", index=False, encoding="utf-8"
    )
    audit.to_csv(metrics / "03_missing_audit.csv", index=False, encoding="utf-8")
    quality.round(3).to_csv(metrics / "04_fill_quality.csv", index=False, encoding="utf-8")
    fill_examples(cleaned).to_csv(
        metrics / "05_fill_examples_telugu.csv", index=False, encoding="utf-8"
    )
    scope.to_csv(metrics / "06_scope_audit.csv", index=False, encoding="utf-8")
    coverage.to_csv(metrics / "07_rating_coverage.csv", index=False, encoding="utf-8")
    weight_table.round(4).to_csv(
        metrics / "08_weights_validation.csv", index=False, encoding="utf-8"
    )
    spread.to_csv(metrics / "09_telugu_test_likes.csv", index=False, encoding="utf-8")
    chart_missing(audit, out / "charts" / "01_missing_before_after.png")
    chart_eval(result, k, out / "charts" / "02_recall_by_method.png")
    chart_fill_quality(quality, out / "charts" / "03_fill_quality.png")
    for table in TABLES:
        (out / "tables" / f"{table}.json").write_text(
            json.dumps(warehouse.snapshot(con, table), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    scripts = sorted(
        p.relative_to(ROOT).as_posix()
        for folder in ("sql", "src", "scripts")
        for p in (ROOT / folder).rglob("*")
        if p.suffix in {".sql", ".py"} and "__pycache__" not in p.parts
    )
    meta = {
        "title": f"{args.sprint}: English + Telugu recommender with fill-don't-drop cleaning",
        "goal": "Recommend films across English and Telugu from one catalogue: fill every missing"
        " field instead of dropping the film, then measure popularity, content, item-item and"
        " hybrid recommenders on what users liked after a cutoff date, overall and on Telugu films.",
        "pattern": "batch ELT: raw -> staging -> marts (DuckDB) + imputation + hybrid recommender",
        "findings": findings(
            scope,
            audit,
            quality,
            coverage,
            result,
            weights,
            spread,
            k,
            staged_rows=len(staged),
            cleaned_rows=len(cleaned),
            excluded=excluded,
            val_users=val_users,
            weight_fallback=fell_back,
            min_val_users=settings.min_validation_users,
        ),
        "commands": [
            "make test",
            "make check",
            "make mutate",
            "make run",
            "make diagram",
            "make results",
        ],
        "scripts": scripts,
        "table_order": list(TABLES),
        "captions": {
            "01_eval_by_slice.csv": {
                "title": f"Recommenders vs the popularity baseline (test window from {test_start.date()})",
                "note": f"Same test users and same candidate films for every method. recall_at_{k} ="
                f" share of the films a user went on to like that appear in their top {k}. Models saw"
                " only ratings before the test window. The Telugu rows allow only Telugu films to be"
                " recommended, for the baseline too. Films released on or after the end of the window are"
                " left out of every method's candidates.",
            },
            "02_bridge_examples.csv": {
                "title": "Cross-language bridge: if you liked this, try these in the other language",
                "note": "Nearest films in the other language by plot text, people and genres (cosine"
                " similarity; 1 = identical). Not rating-based, so it also reaches films nobody has rated.",
            },
            "03_missing_audit.csv": {
                "title": "Missing values before and after cleaning",
                "note": "missing_before from stg_movies, missing_after from mart_movies_clean,"
                " filled_rows = rows carrying the fill flag. No row was dropped.",
            },
            "04_fill_quality.csv": {
                "title": "Are the fills any good? Hidden-value check",
                "note": "10% of real values per language were hidden, filled by the pipeline, and"
                " compared with the truth. naive = the language median, or the language's three most common"
                " genres.",
            },
            "05_fill_examples_telugu.csv": {
                "title": "Telugu films with the most gaps, after filling",
                "note": "(filled) marks a value the pipeline supplied.",
            },
            "06_scope_audit.csv": {
                "title": "Scope: where every landed row went",
                "note": "kept = landed_rows - duplicate_rows - adult_titles - below_vote_floor."
                " Telugu films have no vote floor.",
            },
            "07_rating_coverage.csv": {
                "title": "Rating evidence by language",
                "note": f"likes = ratings of {settings.like_rating} or more.",
            },
            "08_weights_validation.csv": {
                "title": f"Blend weights tried on validation ({val_start.date()} to {test_start.date()})",
                "note": "Each row is one split of 1.0 between content, item-item and popularity,"
                " scored on validation users only. The best row per shelf is the hybrid; a tie goes"
                " to the more content-heavy row.",
            },
            "09_telugu_test_likes.csv": {
                "title": "Which Telugu films the test users went on to like",
                "note": "Likes in the test window by the scored users. cumulative_pct is the running"
                " share of all Telugu test likes.",
            },
            "01_missing_before_after.png": {
                "title": "Share of films missing each field, before and after"
            },
            "02_recall_by_method.png": {"title": f"Recall@{k} by method and slice"},
            "03_fill_quality.png": {"title": "Fill error vs naive fill on hidden real values"},
        },
        "limits": limit_notes(
            settings,
            telugu_test_users=int(
                result[(result["slice"] == "telugu") & (result["method"] == "popularity")][
                    "users"
                ].iloc[0]
            ),
            telugu_val_users=val_users["Telugu shelf"],
            telugu_rated_films=int(coverage.set_index("language").loc["te", "movies_with_ratings"]),
            telugu_films=int(coverage.set_index("language").loc["te", "movies"]),
        ),
        "provenance": {
            "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seconds": round(time.time() - started, 1),
            "settings": asdict(settings),
            "test_start": str(test_start),
            "val_start": str(val_start),
            "weights": weights,
            "movies_file_bytes": movies_file.stat().st_size,
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
            "sklearn": sklearn.__version__,
            "scipy": scipy.__version__,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    con.close()
    say(f"done in {time.time() - started:.0f}s -> results/{args.sprint}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
