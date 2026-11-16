"""Entry point: make recommend LIKE="Inception" LANG=te

Content-based picks from the cleaned catalogue in data/warehouse.duckdb (run `make run` first).
  --like  a film title you liked; repeat the flag for several
  --lang  te, en or any: the language of the films to recommend
"""

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
from scipy import sparse

from cinebridge import recommend
from cinebridge.features import build_item_matrix

ROOT = Path(__file__).resolve().parents[1]


def find(films, title: str) -> int | None:
    """Row of the best-known film whose English or original title equals, else contains, `title`."""
    wanted = title.strip().casefold()
    names = [films["title"].str.casefold(), films["original_title"].fillna("").str.casefold()]
    for match in (lambda s: s == wanted, lambda s: s.str.contains(wanted, regex=False)):
        hit = match(names[0]) | match(names[1])
        if hit.any():
            return int(films[hit]["imdb_votes"].idxmax())
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--like", action="append", required=True)
    parser.add_argument("--lang", choices=("te", "en", "any"), default="any")
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args()
    db = ROOT / "data" / "warehouse.duckdb"
    if not db.exists():
        print("data/warehouse.duckdb not found: run `make run` first", file=sys.stderr)
        return 2
    con = duckdb.connect(str(db), read_only=True)
    films = con.execute("select * from mart_movies_clean order by movie_id").df()
    con.close()
    liked = []
    for title in args.like:
        row = find(films, title)
        if row is None:
            print(f"no film matching {title!r}", file=sys.stderr)
            return 1
        liked.append(row)
        print(
            f"liked: {films['title'][row]} ({films['release_year'][row]}, {films['language'][row]})"
        )
    items = build_item_matrix(films)
    profile = sparse.csr_matrix(
        (np.ones(len(liked), dtype=np.float32), ([0] * len(liked), liked)), shape=(1, len(films))
    )
    candidates = (
        np.ones(len(films), dtype=bool)
        if args.lang == "any"
        else (films["language"] == args.lang).to_numpy()
    )
    scores = recommend.content_scores(profile, items)
    picks, valid = recommend.top_k(scores, profile, candidates, args.k)
    print(f"\n{'#':>2}  {'match':>5}  {'score':>5}  film")
    for rank, (i, ok) in enumerate(zip(picks[0], valid[0], strict=True), start=1):
        if ok and scores[0, i] > 0:
            f = films.iloc[i]
            original = f" / {f['original_title']}" if f["original_title"] != f["title"] else ""
            print(
                f"{rank:>2}  {scores[0, i]:5.3f}  {f['score']:5.2f}  {f['title']}{original}"
                f" ({f['release_year']}, {f['language']}) [{f['genres']}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
