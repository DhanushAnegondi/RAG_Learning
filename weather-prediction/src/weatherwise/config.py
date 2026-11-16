"""Cities the pipeline knows. Add a row to forecast somewhere else."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql://weatherwise:weatherwise@127.0.0.1:15480/weatherwise"


def load_env(path: Path | None = None) -> None:
    """Copy KEY=VALUE lines from .env into the environment, without replacing anything
    already set. Values are never logged."""
    path = path or Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # Notepad adds a BOM
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or key.startswith("#"):
            continue
        if value[:1] in ("'", '"'):
            value = value[1:].partition(value[0])[0]  # up to the closing quote
        else:
            value = value.partition(" #")[0].strip()  # KEY=abc # note
        if value and not os.environ.get(key):  # an empty variable counts as unset
            os.environ[key] = value


def database_url() -> str:
    """Postgres URL from WEATHERWISE_DATABASE_URL, else the local Compose service."""
    return os.environ.get("WEATHERWISE_DATABASE_URL", DEFAULT_DATABASE_URL)


@dataclass(frozen=True)
class City:
    name: str
    latitude: float
    longitude: float
    timezone: str
    unit: str = "C"  # what the site shows by default; storage is always Celsius


CITIES = {
    "torrance": City("torrance", 33.8358, -118.3406, "America/Los_Angeles", "F"),
    "bengaluru": City("bengaluru", 12.9716, 77.5946, "Asia/Kolkata"),
    "chennai": City("chennai", 13.0827, 80.2707, "Asia/Kolkata"),
    "hyderabad": City("hyderabad", 17.3850, 78.4867, "Asia/Kolkata"),
    "mumbai": City("mumbai", 19.0760, 72.8777, "Asia/Kolkata"),
    "delhi": City("delhi", 28.6139, 77.2090, "Asia/Kolkata"),
}
