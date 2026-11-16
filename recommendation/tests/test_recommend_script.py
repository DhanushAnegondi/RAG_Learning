"""scripts/recommend.py: the title lookup behind `make recommend`."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "recommend.py"


@pytest.fixture(scope="module")
def find():
    spec = importlib.util.spec_from_file_location("recommend_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find


def films(*rows: tuple) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["title", "original_title", "imdb_votes"])


def test_an_exact_title_beats_a_higher_voted_partial_match(find):
    df = films(("Inception Rising", "Inception Rising", 900000), ("Inception", "Inception", 10))
    assert find(df, "inception") == 1  # exact match, though film 0 has far more votes


def test_without_an_exact_match_the_best_known_film_containing_the_text_wins(find):
    df = films(
        ("The Dark Knight Rises", "x", 50),
        ("The Dark Knight", "x", 5000),
        ("A Dark Night", "x", 99999),
    )
    assert find(df, "dark knight") == 1  # film 2 does not contain the text


def test_a_telugu_script_original_title_matches(find):
    df = films(("Baahubali: The Beginning", "బాహుబలి", 100), ("Other", "Other", 5))
    assert find(df, "బాహుబలి") == 0


def test_regex_characters_in_the_query_are_literal(find):
    df = films(("Mr. & Mrs. Smith (2005)", "x", 10), ("Mrs Smith", "x", 20))
    assert find(df, "(2005)") == 0
    assert find(df, ".") == 0  # a regex dot would also match film 1 and its higher votes win
    assert find(df, "mr. &") == 0


def test_a_missing_original_title_does_not_break_the_search(find):
    df = films(("Only Title", None, 10))
    assert find(df, "only") == 0


def test_no_match_returns_none(find):
    assert find(films(("Inception", "Inception", 10)), "avatar") is None
