"""Entry point: make fetch. Lands the two source files in data/raw (skips files already there)."""

from pathlib import Path

from cinebridge.config import Settings
from cinebridge.ingest import download, extract_movielens

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> int:
    settings = Settings()
    movies = download(settings.movies_url, RAW / "tmdb_imdb_movies.parquet")
    print(f"movies   {movies.name}  {movies.stat().st_size:,} bytes")
    archive = download(settings.movielens_url, RAW / "ml-32m.zip")
    print(f"ratings  {archive.name}  {archive.stat().st_size:,} bytes")
    for name, path in sorted(extract_movielens(archive, RAW / "movielens").items()):
        print(f"  {name:8s} {path.name}  {path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
