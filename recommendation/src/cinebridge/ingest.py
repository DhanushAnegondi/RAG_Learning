"""Land source files in data/raw: one parquet of movie metadata, one MovieLens zip."""

import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import requests

TIMEOUT_S = 60
CHUNK = 1 << 20
MOVIELENS_MEMBERS = ("ratings.csv", "links.csv")


class IngestError(RuntimeError):
    """A source file could not be landed."""


def download(
    url: str,
    dest: Path,
    session: requests.Session | None = None,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Stream url to dest. An existing dest is kept as is (delete it to refetch).

    The body goes to dest.part and is renamed only when complete, so a cut connection never
    leaves a short file behind. 5xx, 429, connection errors and short bodies are retried with
    1s, 2s, ... waits; other 4xx fail at once.
    """
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    http = session or requests.Session()
    last = "no attempt made"
    for attempt in range(1, retries + 1):
        try:
            resp = http.get(url, stream=True, timeout=TIMEOUT_S)
            try:
                if resp.status_code >= 500 or resp.status_code == 429:
                    last = f"HTTP {resp.status_code}"
                elif resp.status_code != 200:
                    raise IngestError(f"HTTP {resp.status_code} for {url}")
                else:
                    written = 0
                    with part.open("wb") as f:
                        for chunk in resp.iter_content(CHUNK):
                            f.write(chunk)
                            written += len(chunk)
                    # requests decodes gzip, so a Content-Length of the encoded body would not match
                    encoded = resp.headers.get("Content-Encoding")
                    expected = None if encoded else resp.headers.get("Content-Length")
                    if expected is None or int(expected) == written:
                        part.replace(dest)
                        return dest
                    last = f"short body: {written} of {expected} bytes"
            finally:
                resp.close()
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        part.unlink(missing_ok=True)
        if attempt < retries:
            sleep(float(attempt))
    raise IngestError(f"gave up on {url} after {retries} attempts ({last})")


def extract_movielens(zip_path: Path, out_dir: Path) -> dict[str, Path]:
    """Pull ratings.csv and links.csv out of the MovieLens zip into out_dir.

    Members are matched by exact base name and written under fixed names, so nothing in the
    archive can choose where a file lands.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if base in MOVIELENS_MEMBERS and base not in {p.name for p in found.values()}:
                target = out_dir / base
                with z.open(info) as src, target.open("wb") as dst:
                    while chunk := src.read(CHUNK):
                        dst.write(chunk)
                found[base.removesuffix(".csv")] = target
    missing = [m for m in MOVIELENS_MEMBERS if m.removesuffix(".csv") not in found]
    if missing:
        raise IngestError(f"{zip_path} has no {', '.join(missing)}")
    return found
