"""Cities the pipeline knows. Add a row to forecast somewhere else."""

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    latitude: float
    longitude: float
    timezone: str


CITIES = {
    "bengaluru": City("bengaluru", 12.9716, 77.5946, "Asia/Kolkata"),
    "chennai": City("chennai", 13.0827, 80.2707, "Asia/Kolkata"),
    "hyderabad": City("hyderabad", 17.3850, 78.4867, "Asia/Kolkata"),
    "mumbai": City("mumbai", 19.0760, 72.8777, "Asia/Kolkata"),
    "delhi": City("delhi", 28.6139, 77.2090, "Asia/Kolkata"),
}
