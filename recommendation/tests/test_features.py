"""Item vectors: what may and may not make two films look alike."""

import numpy as np
import pytest

from cinebridge import clean
from cinebridge.features import build_item_matrix


def cosine(x, i: int, j: int) -> float:
    return float(x[i].multiply(x[j]).sum())


def test_a_film_with_every_field_is_unit_length_and_a_film_with_gaps_is_shorter(
    make_frame, make_movie
):
    df = make_frame(make_movie(3), make_movie(1, overview=None, keywords=None), make_movie(2))
    x = build_item_matrix(df, min_df=1)
    assert x.shape[0] == 3
    norms = np.sqrt(x.multiply(x).sum(axis=1)).A1
    # block weights: text 1.0, people 0.6, genres 0.6 -> a film with no text keeps
    # sqrt(0.36 + 0.36) / sqrt(1 + 0.36 + 0.36) of the length
    assert norms == pytest.approx([1.0, np.sqrt(0.72 / 1.72), 1.0])
    assert cosine(x, 0, 0) == pytest.approx(1.0)


def test_a_film_with_gaps_does_not_outrank_a_fuller_match(make_frame, make_movie):
    """Found on the real run: genre-only films topped every list at exactly the same score."""
    df = make_frame(
        make_movie(1, overview="rebels fight the empire kingdom", genres="Action, Drama"),
        make_movie(2, overview="rebels sail the ocean storm", genres="Action, Drama"),
        make_movie(
            3, overview=None, keywords=None, directors=None, cast_names=None, genres="Action, Drama"
        ),
    )
    x = build_item_matrix(df, min_df=1)
    assert cosine(x, 0, 1) > cosine(x, 0, 2) > 0
    # the genre-only film matches on genres alone: 0.36 of the 1.72 total weight
    assert cosine(x, 0, 2) == pytest.approx(0.36 / 1.72)


def test_shared_director_makes_films_more_alike(make_frame, make_movie):
    df = make_frame(
        make_movie(1, directors="S.S. Rajamouli", genres="Action"),
        make_movie(2, directors="S.S. Rajamouli", genres="Action"),
        make_movie(3, directors="Other Person", genres="Action"),
    )
    x = build_item_matrix(df, min_df=1)
    assert cosine(x, 0, 1) > cosine(x, 0, 2) > 0


def test_unknown_people_are_not_a_similarity_signal(make_frame, make_movie):
    df = make_frame(
        make_movie(1, directors=None, cast_names=None, genres="Action"),
        make_movie(2, directors=None, cast_names=None, genres="Comedy"),
    )
    filled = clean.fill_people(df)
    assert filled["directors"].tolist() == ["Unknown", "Unknown"]
    x = build_item_matrix(filled, min_df=1)
    assert cosine(x, 0, 1) == 0.0


def test_filled_overview_and_keywords_are_not_a_similarity_signal(make_frame, make_movie):
    df = make_frame(
        make_movie(1, overview=None, keywords=None, genres="Action", directors="A", cast_names="P"),
        make_movie(2, overview=None, keywords=None, genres="Comedy", directors="B", cast_names="Q"),
    )
    out = clean.clean_movies(df, min_df=1)
    assert out["overview"].str.contains("film directed by").all()
    x = build_item_matrix(out, min_df=1)
    assert cosine(x, 0, 1) == 0.0


def test_language_is_not_a_wall_between_similar_films(make_frame, make_movie):
    df = make_frame(
        make_movie(
            1, language="en", overview="a warrior prince reclaims his kingdom", genres="Action"
        ),
        make_movie(
            2, language="te", overview="a warrior prince fights for the kingdom", genres="Action"
        ),
        make_movie(3, language="te", overview="two friends open a bakery", genres="Comedy"),
    )
    x = build_item_matrix(df, min_df=1)
    assert cosine(x, 0, 1) > 0.3
    assert cosine(x, 0, 2) == 0.0


def test_only_the_first_five_cast_names_count(make_frame, make_movie):
    df = make_frame(
        make_movie(1, cast_names="A, B, C, D, E, Shared Extra", genres="Action"),
        make_movie(2, cast_names="V, W, X, Y, Z, Shared Extra", genres="Comedy"),
    )
    x = build_item_matrix(df, min_df=1)
    assert cosine(x, 0, 1) == 0.0


def test_a_film_with_no_usable_fields_gets_a_zero_vector(make_frame, make_movie):
    df = make_frame(
        make_movie(1),
        make_movie(2, overview=None, keywords=None, directors=None, cast_names=None, genres=None),
    )
    x = build_item_matrix(df, min_df=1)
    assert x[1].nnz == 0
    assert np.isfinite(x.data).all()


def test_genres_can_be_left_out(make_frame, make_movie):
    df = make_frame(
        make_movie(1, genres="Action"),
        make_movie(2, genres="Action"),
    )
    assert cosine(build_item_matrix(df, min_df=1), 0, 1) > 0
    assert cosine(build_item_matrix(df, min_df=1, include_genres=False), 0, 1) == 0.0


def test_literal_unknown_person_without_a_flag_is_not_a_similarity_signal(make_frame, make_movie):
    """No `_filled` column here: only the placeholder text itself marks these as unknown."""
    df = make_frame(
        make_movie(1, directors="Unknown", cast_names="Unknown", genres="Action"),
        make_movie(2, directors="Unknown", cast_names="Unknown", genres="Comedy"),
    )
    assert "directors_filled" not in df
    assert cosine(build_item_matrix(df, min_df=1), 0, 1) == 0.0


def test_filled_genres_are_not_a_similarity_signal(make_frame, make_movie):
    """Two films that both had no genres and were given the language favourite must not match."""
    blank = {"overview": None, "keywords": None, "directors": None, "cast_names": None}
    rows = [make_movie(i, language="te", genres="Action") for i in (1, 2, 3)]
    rows += [make_movie(4, language="te", genres=None, **blank)]
    rows += [make_movie(5, language="te", genres=None, **blank)]
    out = clean.clean_movies(make_frame(*rows), min_df=1)
    assert out["genres_fill_method"].tolist()[3:] == ["language_mode", "language_mode"]
    assert out["genres"].tolist()[3:] == ["Action", "Action"]  # still there for display
    x = build_item_matrix(out, min_df=1)
    assert cosine(x, 3, 4) == 0.0
    assert cosine(x, 0, 3) == 0.0  # and a filled genre does not match an observed one either


def test_observed_genres_still_match_when_another_row_was_filled(make_frame, make_movie):
    df = make_frame(
        make_movie(1, genres="Action"),
        make_movie(2, genres="Action"),
        make_movie(3, genres="Action"),
    )
    df["genres_filled"] = [False, False, True]
    x = build_item_matrix(df, min_df=1)
    assert cosine(x, 0, 1) > 0
    assert cosine(x, 0, 2) == 0.0
