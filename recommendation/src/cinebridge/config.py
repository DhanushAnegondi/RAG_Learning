"""Run settings. One place for sources and thresholds; pass a Settings object, never globals."""

from dataclasses import dataclass

MOVIES_URL = (
    "https://huggingface.co/api/datasets/HenryWaltson/TMDB-IMDB-Movies-Dataset"
    "/parquet/default/train/0.parquet"
)
MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/ml-32m.zip"


@dataclass(frozen=True)
class Settings:
    movies_url: str = MOVIES_URL
    movielens_url: str = MOVIELENS_URL
    en_min_votes: int = 1000  # English films need this many IMDb votes; Telugu films are all kept
    like_rating: float = 4.0  # a rating at or above this is a "like"
    test_months: int = 12  # last months of ratings, held out for the final numbers
    val_months: int = 12  # the months before that, used only to pick the blend weight
    k: int = 10
    min_profile_likes: int = 5
    cf_user_mod: int = 8  # item-item similarity is learned from users with user_id % mod == 0
    cf_neighbors: int = 50
    cf_shrink: float = 5.0
    genre_neighbors: int = 10
    weight_step: float = 0.25  # blend weights tried on validation are multiples of this
    min_validation_users: int = 30  # fewer: the shelf borrows the all-films weights
    seed: int = 7
