"""Cities the pipeline knows. Add a row to forecast somewhere else."""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql://weatherwise:weatherwise@127.0.0.1:15480/weatherwise"


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
