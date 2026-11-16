"""Shared builders. Tests are offline: frames and files are built here, nothing is downloaded."""

from datetime import date

import pandas as pd
import pytest

STG_COLUMNS = [
    "movie_id",
    "imdb_id",
    "title",
    "original_title",
    "language",
    "status",
    "release_date",
    "release_year",
    "runtime_min",
    "overview",
    "tagline",
    "genres",
    "keywords",
    "directors",
    "cast_names",
    "imdb_rating",
    "imdb_votes",
    "popularity",
]


def movie(movie_id: int, **over) -> dict:
    """One staged movie row with every field observed; override fields to make gaps."""
    row = {
        "movie_id": movie_id,
        "imdb_id": f"tt{movie_id:07d}",
        "title": f"Film {movie_id}",
        "original_title": f"Film {movie_id}",
        "language": "en",
        "status": "Released",
        "release_date": date(2000, 1, 1),
        "release_year": 2000,
        "runtime_min": 100,
        "overview": f"story{movie_id} about place{movie_id}",
        "tagline": None,
        "genres": "Drama",
        "keywords": f"kw{movie_id}",
        "directors": f"Director {movie_id}",
        "cast_names": f"Actor {movie_id}",
        "imdb_rating": 7.0,
        "imdb_votes": 1000,
        "popularity": 1.0,
    }
    unknown = set(over) - set(row)
    if unknown:
        raise KeyError(f"unknown movie fields: {sorted(unknown)}")
    row.update(over)
    return row


def frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=STG_COLUMNS)


@pytest.fixture
def make_frame():
    return frame


@pytest.fixture
def make_movie():
    return movie
