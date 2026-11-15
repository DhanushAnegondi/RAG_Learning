"""Parity check for the Postgres port: the same data and models must give the same numbers.

Compares every metrics CSV of two sprint folders cell by cell. Run:
  .venv/Scripts/python scripts/compare_frozen.py sprint-02 sprint-03
Numbers may differ by `tol`; anything else is listed. Exit code 1 if any file differs.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RENAMED = {"band_p10_p90_c": "start_band_c"}  # sprint-03 review: clearer column name


def _text(v) -> str:
    return "" if pd.isna(v) else str(v)


def compare(old: Path, new: Path, tol: float) -> list[str]:
    a, b = pd.read_csv(old).rename(columns=RENAMED), pd.read_csv(new)
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return [f"shape or columns differ: {a.shape} {list(a.columns)} vs {b.shape}"]
    out = []
    for col in a.columns:
        x, y = pd.to_numeric(a[col], errors="coerce"), pd.to_numeric(b[col], errors="coerce")
        numeric = x.notna() & y.notna()
        bad = numeric & ((x - y).abs() > tol)
        other = ~numeric & (a[col].map(_text) != b[col].map(_text))
        for i in a.index[bad | other]:
            out.append(f"row {i} {col}: {a.loc[i, col]} -> {b.loc[i, col]}")
    return out


def main(old: str, new: str, tol: float = 0.011) -> int:
    failed = 0
    for path in sorted((ROOT / "results" / old / "metrics").glob("*.csv")):
        other = ROOT / "results" / new / "metrics" / path.name
        diffs = compare(path, other, tol) if other.exists() else ["missing in " + new]
        print(
            f"{'SAME' if not diffs else 'DIFF'} {path.name}"
            + "".join(f"\n  {d}" for d in diffs[:12])
        )
        failed += bool(diffs)
    print(f"\n{failed} file(s) differ beyond {tol}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
