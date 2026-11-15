"""What the user saw on a day: validate, convert to Celsius, store. Storage is always Celsius."""

from datetime import date, datetime

import pandas as pd
import psycopg

from weatherwise import warehouse

LIMIT_C = (-60.0, 60.0)  # same fence as the cleaning rules in sql/staging


def to_celsius(value: float | None, unit: str) -> float | None:
    if unit not in ("C", "F"):
        raise ValueError(f"unknown unit {unit!r}; use C or F")
    if value is None:
        return None
    return round((value - 32) * 5 / 9, 2) if unit == "F" else float(value)


def validate(
    day: date, tmax: float | None, tmin: float | None, unit: str, today: date
) -> tuple[float | None, float | None]:
    """Returns (tmax_c, tmin_c) or raises ValueError with a reason the user can act on."""
    tmax_c, tmin_c = to_celsius(tmax, unit), to_celsius(tmin, unit)
    if day > today:
        raise ValueError(f"{day} is in the future; enter a day up to {today}")
    if tmax_c is None and tmin_c is None:
        raise ValueError("enter at least one of the day's high or low")
    for label, v in (("high", tmax_c), ("low", tmin_c)):
        if v is not None and not LIMIT_C[0] <= v <= LIMIT_C[1]:
            raise ValueError(f"{label} of {v} C is outside {LIMIT_C[0]:.0f}..{LIMIT_C[1]:.0f} C")
    if tmax_c is not None and tmin_c is not None and tmax_c < tmin_c:
        raise ValueError("the high is below the low")
    return tmax_c, tmin_c


def save(
    con: psycopg.Connection,
    city: str,
    day: date,
    tmax: float | None,
    tmin: float | None,
    unit: str,
    *,
    today: date,
    note: str | None = None,
) -> None:
    tmax_c, tmin_c = validate(day, tmax, tmin, unit, today)
    if note and "\x00" in note:
        raise ValueError("the note contains a character that cannot be stored")
    row = {
        "city": city,
        "date": pd.Timestamp(day),
        "tmax_c": tmax_c,
        "tmin_c": tmin_c,
        "note": note,
        "entered_at": pd.Timestamp(datetime.now().replace(microsecond=0)),
    }
    df = pd.DataFrame([row]).astype({"tmax_c": "float64", "tmin_c": "float64", "note": "object"})
    warehouse.load(con, "user_observation", df)


def delete(con: psycopg.Connection, city: str, day: date) -> None:
    warehouse.run_sql_file(
        con, warehouse.SQL_DIR / "raw" / "delete_user_observation.sql", {"city": city, "day": day}
    )
