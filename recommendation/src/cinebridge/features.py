"""Item vectors for "films like this one": plot text, people and genres, one unit-length row each.

Only real information may make two films look alike. A value the cleaning step filled in
(a built overview, derived keywords, the "Unknown" person placeholder, a filled genre) is left
out here, so two films never match just because both had the same gap. Filled genres stay in the
table for display.
"""

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

UNKNOWN = "Unknown"
TEXT_WEIGHT, PEOPLE_WEIGHT, GENRE_WEIGHT = 1.0, 0.6, 0.6
MAX_CAST = 5


def split_list(value: object) -> list[str]:
    """'A, B , C' -> ['A', 'B', 'C']; missing -> []."""
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _usable(df: pd.DataFrame, col: str) -> list[str]:
    """Column values that were observed in the source; '' for missing or filled values."""
    values = df[col]
    ok = values.notna().to_numpy()
    flag = f"{col}_filled"
    if flag in df:
        ok = ok & ~df[flag].to_numpy(dtype=bool)
    return [
        str(v) if keep and str(v) != UNKNOWN else "" for v, keep in zip(values, ok, strict=True)
    ]


def _identity(tokens: list[str]) -> list[str]:
    return tokens


def _tfidf(docs: list, min_df: int, **kwargs) -> sparse.csr_matrix:
    try:
        return TfidfVectorizer(
            min_df=min_df, sublinear_tf=True, dtype=np.float32, **kwargs
        ).fit_transform(docs)
    except ValueError:  # nothing left to count (all docs empty, or every term below min_df)
        return sparse.csr_matrix((len(docs), 0), dtype=np.float32)


def build_item_matrix(
    df: pd.DataFrame, min_df: int = 2, include_genres: bool = True
) -> sparse.csr_matrix:
    """One sparse row per film, in frame order. Similarity of two films = row dot row.

    Each block (text, people, genres) is unit length or empty, and the blocks are joined with
    fixed weights. A film with every block has length 1; a film missing a block is shorter, so
    it can match another film only on what it really has. (Rescaling every row to length 1
    would hand a film with nothing but genres the full weight on genres, and it would top
    every list.)
    """
    overview, keywords = _usable(df, "overview"), _usable(df, "keywords")
    text = [f"{o} {k}".strip() for o, k in zip(overview, keywords, strict=True)]
    people = [
        [f"dir:{n}" for n in split_list(d)] + [f"cast:{n}" for n in split_list(c)[:MAX_CAST]]
        for d, c in zip(_usable(df, "directors"), _usable(df, "cast_names"), strict=True)
    ]
    weights = [TEXT_WEIGHT, PEOPLE_WEIGHT]
    blocks = [
        TEXT_WEIGHT * _tfidf(text, min_df, stop_words="english", max_features=60000),
        PEOPLE_WEIGHT * _tfidf(people, min_df, analyzer=_identity),
    ]
    if include_genres:
        genres = [split_list(g) for g in _usable(df, "genres")]
        weights.append(GENRE_WEIGHT)
        blocks.append(GENRE_WEIGHT * _tfidf(genres, 1, analyzer=_identity))
    full_length = np.float32(np.sqrt(sum(w * w for w in weights)))
    return sparse.csr_matrix(sparse.hstack(blocks, format="csr", dtype=np.float32) / full_length)
