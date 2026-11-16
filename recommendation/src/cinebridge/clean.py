"""Fill missing film metadata. No row is ever dropped for having a gap.

Every fill_* function returns a copy with the gap filled and a `<column>_filled` flag that
marks exactly the rows it filled. Observed values are never changed, and every statistic used
for a fill (median, mean, favourite genre) is computed from observed values only.

  title        original title, else "Untitled <id>"
  release_year median year of the most similar films (shared cast, director, plot words),
               else the median year of the film's language
  directors    "Unknown" (a placeholder; features.py never treats it as a real person)
  cast_names   "Unknown"
  genres       genres of the most similar films (plot text + people), else the language favourite.
               A filled genre is for display; features.py does not use it as a similarity signal.
  overview     one sentence built from the film's own genres, director, cast and tagline
  keywords     strongest words of the film's own overview, else its genres
  runtime_min  median of the language + first genre group, else of the language
  imdb_rating  mean rating of the language; `score` shrinks every rating toward that mean
               by how few votes back it
"""

from collections import Counter

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from cinebridge.features import UNKNOWN, build_item_matrix, split_list

FILLED_COLUMNS = (
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
)
MASKABLE = ("runtime_min", "release_year", "genres")
MAX_GENRES = 3
CHUNK = 512


class CleanError(RuntimeError):
    """Cleaning cannot fill a column, or would break the no-row-dropped promise."""


def _flag(mask: pd.Series) -> np.ndarray:
    return mask.to_numpy(dtype=bool)


def fill_title(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    miss = out["title"].isna()
    label = "Untitled " + out["movie_id"].astype(str)
    fallback = out["original_title"].where(out["original_title"].notna(), label)
    out["title"] = out["title"].where(~miss, fallback)
    out["title_filled"] = _flag(miss)
    return out


def _fill_number(df: pd.DataFrame, col: str, fill: pd.Series) -> pd.DataFrame:
    out = df.copy()
    values = pd.to_numeric(out[col], errors="coerce").astype("float64")
    miss = values.isna()
    out[col] = values.where(~miss, fill).round().astype("int64")
    out[f"{col}_filled"] = _flag(miss)
    return out


def _neighbours(x, rows: np.ndarray, known: np.ndarray, k: int):
    """For each row, the positions (within `known`) of its k most similar films with a
    similarity above zero, and those similarities. Yields (row, positions, similarities)."""
    known_t = x[known].T.tocsr()
    for start in range(0, len(rows), CHUNK):
        part = rows[start : start + CHUNK]
        sims = (x[part] @ known_t).toarray()
        for row, sim in zip(part, sims, strict=True):
            top = np.argsort(-sim, kind="stable")[:k]
            top = top[sim[top] > 0]
            yield row, top, sim[top]


def fill_year(df: pd.DataFrame, k: int = 10, min_df: int = 2) -> pd.DataFrame:
    """Missing year = median year of the k most similar films (plot text + people).

    Films share actors and directors with films of the same era, which says far more than the
    language as a whole. A film with nothing in common with any other gets the median year of
    its language (all films, if the language has no observed year).
    """
    years = pd.to_numeric(df["release_year"], errors="coerce").astype("float64")
    seen = years.notna()
    if not seen.any():
        raise CleanError("release_year: no observed value to fill from")
    by_language = years[seen].groupby(df.loc[seen, "language"]).median()
    fill = df["language"].map(by_language).astype("float64").fillna(years[seen].median())
    missing, known = np.flatnonzero(~seen), np.flatnonzero(seen)
    if len(missing):
        x = build_item_matrix(df, min_df=min_df, include_genres=False)
        known_years = years.to_numpy()[known]
        for row, top, _ in _neighbours(x, missing, known, k):
            if len(top):
                fill.iloc[row] = float(np.median(known_years[top]))
    return _fill_number(df, "release_year", fill)


def fill_runtime(df: pd.DataFrame, min_group: int = 5) -> pd.DataFrame:
    """Median runtime of films in the same language with the same first genre.

    A group with fewer than min_group observed runtimes is too thin: use the language median,
    and the all-film median if the language has no observed runtime at all.
    """
    runtime = pd.to_numeric(df["runtime_min"], errors="coerce").astype("float64")
    seen = runtime.notna()
    if not seen.any():
        raise CleanError("runtime_min: no observed value to fill from")
    first_genre = pd.Series([(split_list(g) or [""])[0] for g in df["genres"]], index=df.index)
    observed = pd.DataFrame({"language": df["language"], "genre": first_genre, "runtime": runtime})[
        seen
    ]
    groups = observed.groupby(["language", "genre"])["runtime"].agg(["median", "count"])
    group_median = groups.loc[groups["count"] >= min_group, "median"].to_dict()
    by_group = pd.Series(
        [group_median.get(key, np.nan) for key in zip(df["language"], first_genre, strict=True)],
        index=df.index,
        dtype="float64",
    )
    by_language = df["language"].map(observed.groupby("language")["runtime"].median())
    fill = by_group.fillna(by_language.astype("float64")).fillna(observed["runtime"].median())
    return _fill_number(df, "runtime_min", fill)


def fill_people(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("directors", "cast_names"):
        miss = out[col].isna()
        out[col] = out[col].where(~miss, UNKNOWN)
        out[f"{col}_filled"] = _flag(miss)
    return out


def _language_favourite(df: pd.DataFrame, known: np.ndarray) -> dict[str | None, str]:
    """Most common single genre per language among films with observed genres (None = all)."""
    counts: dict[str | None, Counter] = {None: Counter()}
    for language, genres in zip(df["language"][known], df["genres"][known], strict=True):
        names = split_list(genres)
        counts.setdefault(language, Counter()).update(names)
        counts[None].update(names)
    return {
        key: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for key, c in counts.items() if c
    }


def _vote(similarity: np.ndarray, neighbour_genres: list[list[str]]) -> str:
    """Genres of the neighbours, each weighted by similarity; keep those with at least half
    the top weight (at most MAX_GENRES)."""
    weight: dict[str, float] = {}
    for sim, names in zip(similarity, neighbour_genres, strict=True):
        for name in names:
            weight[name] = weight.get(name, 0.0) + float(sim)
    ranked = sorted(weight.items(), key=lambda kv: (-round(kv[1], 6), kv[0]))
    floor = 0.5 * ranked[0][1] - 1e-6
    return ", ".join(name for name, w in ranked[:MAX_GENRES] if w >= floor)


def fill_genres(df: pd.DataFrame, k: int = 10, min_df: int = 2) -> pd.DataFrame:
    """Missing genres come from the k most similar films that have observed genres.

    Similarity uses plot text and people only (not genres). A film with nothing in common
    with any other film gets its language's most common genre.
    """
    out = df.copy()
    miss = out["genres"].isna().to_numpy()
    out["genres_filled"] = miss
    out["genres_fill_method"] = np.where(miss, "language_mode", "observed")
    if not miss.any():
        return out
    known = ~miss
    if not known.any():
        raise CleanError("genres: no observed value to fill from")
    favourite = _language_favourite(out, known)
    x = build_item_matrix(out, min_df=min_df, include_genres=False)
    known_idx, miss_idx = np.flatnonzero(known), np.flatnonzero(miss)
    known_genres = [split_list(g) for g in out["genres"].to_numpy()[known_idx]]
    genres = out["genres"].astype(object).to_numpy(copy=True)
    method = out["genres_fill_method"].to_numpy(copy=True)
    languages = out["language"].to_numpy()
    for row, top, sims in _neighbours(x, miss_idx, known_idx, k):
        if len(top):
            genres[row] = _vote(sims, [known_genres[j] for j in top])
            method[row] = "neighbours"
        else:
            genres[row] = favourite.get(languages[row], favourite[None])
    out["genres"] = genres
    out["genres_fill_method"] = method
    return out


def _real_people(df: pd.DataFrame, col: str) -> list[list[str]]:
    return [[] if v == UNKNOWN else split_list(v) for v in df[col]]


def fill_overview(df: pd.DataFrame) -> pd.DataFrame:
    """Build a one-line overview from the film's own fields. Needs genres filled first."""
    out = df.copy()
    miss = out["overview"].isna().to_numpy()
    if miss.any() and out.loc[miss, "genres"].isna().any():
        raise CleanError("overview: fill genres before overview")
    directors, cast = _real_people(out, "directors"), _real_people(out, "cast_names")
    built = []
    for i in np.flatnonzero(miss):
        text = f"{out['genres'].iloc[i]} film"
        if directors[i]:
            text += f" directed by {', '.join(directors[i])}"
        if cast[i]:
            text += f", starring {', '.join(cast[i][:3])}"
        text += "."
        tagline = out["tagline"].iloc[i]
        if isinstance(tagline, str) and tagline.strip():
            text += f" {tagline.strip()}"
        built.append(text)
    overview = out["overview"].astype(object).to_numpy(copy=True)
    overview[miss] = built
    out["overview"] = overview
    out["overview_filled"] = miss
    return out


def fill_keywords(df: pd.DataFrame, top_n: int = 5, min_df: int = 2) -> pd.DataFrame:
    """Missing keywords = the top_n strongest words (TF-IDF) of the film's own observed
    overview. A film whose overview was itself filled gets its genres as keywords."""
    out = df.copy()
    miss = out["keywords"].isna().to_numpy()
    real_overview = out["overview"].notna().to_numpy()
    if "overview_filled" in out:
        real_overview = real_overview & ~out["overview_filled"].to_numpy(dtype=bool)
    keywords = out["keywords"].astype(object).to_numpy(copy=True)
    from_text = np.flatnonzero(miss & real_overview)
    if len(from_text):
        try:
            vec = TfidfVectorizer(stop_words="english", min_df=min_df, sublinear_tf=True)
            vec.fit(out["overview"].to_numpy()[real_overview])
            terms = vec.get_feature_names_out()
            weights = vec.transform(out["overview"].to_numpy()[from_text]).tocsr()
            for n, row in enumerate(from_text):
                w = weights[n]
                order = sorted(zip(-w.data, terms[w.indices], strict=True))[:top_n]
                if order:
                    keywords[row] = ", ".join(term for _, term in order)
        except ValueError:  # no usable vocabulary; the genre fallback below covers these rows
            pass
    for row in np.flatnonzero(miss):
        if not isinstance(keywords[row], str):
            names = split_list(out["genres"].iloc[row])
            if not names:
                raise CleanError("keywords: fill genres before keywords")
            keywords[row] = ", ".join(name.lower() for name in names)
    out["keywords"] = keywords
    out["keywords_filled"] = miss
    return out


def fill_rating(df: pd.DataFrame) -> pd.DataFrame:
    """Fill a missing rating with the language mean, and add `score`:

        score = (v * R + m * C) / (v + m)

    R = film rating, v = its votes, C = mean rating of the language, m = median votes of the
    language. A film with few votes sits near C; a film with many votes keeps its own rating.
    """
    out = df.copy()
    rating = pd.to_numeric(out["imdb_rating"], errors="coerce").astype("float64")
    votes = pd.to_numeric(out["imdb_votes"], errors="coerce").astype("float64")
    no_rating, no_votes = rating.isna(), votes.isna()
    if no_rating.all():
        raise CleanError("imdb_rating: no observed value to fill from")
    language = out["language"]
    mean = language.map(rating[~no_rating].groupby(language[~no_rating]).mean())
    mean = mean.astype("float64").fillna(rating[~no_rating].mean())
    weight = language.map(votes[~no_votes].groupby(language[~no_votes]).median())
    weight = weight.astype("float64").fillna(votes[~no_votes].median()).fillna(0.0)
    rating, votes = rating.where(~no_rating, mean), votes.where(~no_votes, 0.0)
    total = votes + weight
    score = (votes * rating + weight * mean) / total.where(total > 0, 1.0)
    out["imdb_rating"] = rating
    out["imdb_votes"] = votes.astype("int64")
    out["score"] = score.where(total > 0, mean)
    out["imdb_rating_filled"] = _flag(no_rating)
    out["imdb_votes_filled"] = _flag(no_votes)
    return out


def clean_movies(
    df: pd.DataFrame, k: int = 10, min_df: int = 2, min_group: int = 5
) -> pd.DataFrame:
    """Run every fill in dependency order and prove no row was lost and no gap is left."""
    out = fill_people(fill_year(fill_title(df), k=k, min_df=min_df))
    out = fill_genres(out, k=k, min_df=min_df)
    out = fill_keywords(fill_overview(out), min_df=min_df)
    out = fill_rating(fill_runtime(out, min_group=min_group))
    if out["movie_id"].tolist() != df["movie_id"].tolist():
        raise CleanError(f"rows changed: {len(df)} in, {len(out)} out")
    for col in (*FILLED_COLUMNS, "score"):
        left = int(out[col].isna().sum())
        if left:
            raise CleanError(f"{col}: {left} values still missing after cleaning")
    return out


def _top_genres(genres: pd.Series, n: int) -> set[str]:
    """The n most common single genres (ties alphabetical)."""
    counts = Counter(name for g in genres for name in split_list(g))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {name for name, _ in ranked[:n]}


def masked_fill_check(
    df: pd.DataFrame,
    frac: float = 0.1,
    seed: int = 7,
    k: int = 10,
    min_df: int = 2,
    min_group: int = 5,
) -> pd.DataFrame:
    """How good are the fills? Hide a share of real values, fill them, compare with the truth.

    For runtime, year and genres: hide `frac` of the observed values in each language, run the
    same fill the pipeline uses, and score it against the hidden values. Values the pipeline
    filled earlier are treated as missing too, so the fill sees observed values only, exactly
    as it does in the pipeline; only the hidden rows are scored.
    The naive column is the fair simple baseline: the film's own language median of the values
    left (runtime, year), or that language's three commonest genres (the fill also offers at
    most three). Numbers: mean absolute error. Genres: share of films where no guessed genre
    is a real one.
    """
    rng = np.random.default_rng(seed)
    fills = {
        "runtime_min": lambda d: fill_runtime(d, min_group=min_group),
        "release_year": lambda d: fill_year(d, k=k, min_df=min_df),
        "genres": lambda d: fill_genres(d, k=k, min_df=min_df),
    }
    units = {"runtime_min": "mean abs error, minutes", "release_year": "mean abs error, years"}
    languages = df["language"].to_numpy()
    rows = []
    for col in MASKABLE:
        flag = f"{col}_filled"
        observed = ~df[flag].to_numpy(dtype=bool) if flag in df else df[col].notna().to_numpy()
        picks = []
        for language in sorted(set(languages)):
            pool = np.flatnonzero(observed & (languages == language))
            picks.append(rng.choice(pool, size=round(frac * len(pool)), replace=False))
        pick = np.sort(np.concatenate(picks))
        hidden = np.zeros(len(df), dtype=bool)
        hidden[pick] = True
        masked = df.copy()
        masked[col] = masked[col].astype("float64" if col != "genres" else object)
        masked.loc[hidden | ~observed, col] = np.nan
        guess = fills[col](masked)[col].to_numpy()[pick]
        truth = df[col].to_numpy()[pick]
        left = observed & ~hidden
        if col == "genres":
            commonest = {
                lang: _top_genres(df[col][left & (languages == lang)], MAX_GENRES)
                for lang in set(languages)
            }
            error = np.array(
                [
                    not set(split_list(g)) & set(split_list(t))
                    for g, t in zip(guess, truth, strict=True)
                ],
                dtype=float,
            )
            naive = np.array(
                [
                    not commonest[lang] & set(split_list(t))
                    for lang, t in zip(languages[pick], truth, strict=True)
                ],
                dtype=float,
            )
        else:
            median = {
                lang: float(df[col][left & (languages == lang)].astype(float).median())
                for lang in set(languages)
            }
            error = np.abs(guess.astype(float) - truth.astype(float))
            naive = np.abs(
                np.array([median[lang] for lang in languages[pick]]) - truth.astype(float)
            )
        for language in ("all", *sorted(set(languages))):
            part = (
                np.ones(len(pick), dtype=bool) if language == "all" else languages[pick] == language
            )
            if part.any():
                rows.append(
                    {
                        "column_name": col,
                        "language": language,
                        "metric": units.get(col, "share with no correct genre"),
                        "masked_rows": int(part.sum()),
                        "fill_error": float(error[part].mean()),
                        "naive_error": float(naive[part].mean()),
                    }
                )
    return pd.DataFrame(rows)
