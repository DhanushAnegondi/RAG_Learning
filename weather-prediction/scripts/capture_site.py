"""Screenshot every tab of the running site into results/<sprint>/site/ (evidence for the
results page and README). The site must be up: make site.

Run: .venv/Scripts/python scripts/capture_site.py sprint-03
It saves one example reading through the page (10 days ago, the grid value plus 1 C), captures
the comparison and the scoreboard, then deletes that reading again.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = "http://localhost:8000"
CITY = "torrance"


def main(sprint: str) -> int:
    out = ROOT / "results" / sprint / "site"
    out.mkdir(parents=True, exist_ok=True)
    day = date.today() - timedelta(days=10)
    existing = requests.get(f"{URL}/api/observations", params={"city": CITY}, timeout=30).json()
    if any(o["date"] == day.isoformat() for o in existing):
        print(f"an entry for {day} already exists; not touching it")
        return 1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1180, "height": 900}, color_scheme="light")
            page.goto(URL)
            page.wait_for_selector("#week .card")
            page.screenshot(path=out / "forecast.png", full_page=True)

            page.click("[data-tab=check]")
            page.fill("#entry [name=date]", day.isoformat())
            page.fill("#entry [name=tmax]", "75")
            page.fill("#entry [name=tmin]", "58")
            page.select_option("#entry [name=unit]", "F")
            page.fill("#entry [name=note]", "example reading for the screenshot")
            page.click("#entry button[type=submit]")
            page.wait_for_selector("#check-result .verdict")
            page.wait_for_selector("#entries table")
            page.set_viewport_size({"width": 1180, "height": 1250})
            page.screenshot(path=out / "check.png")

            page.set_viewport_size({"width": 1180, "height": 900})
            page.click("[data-tab=score]")
            page.wait_for_selector("#score-tiles .tile")
            page.screenshot(path=out / "scoreboard.png")

            page.click("[data-tab=record]")
            page.wait_for_selector("#board table")
            page.set_viewport_size({"width": 1180, "height": 1500})
            page.screenshot(path=out / "record.png")

            page.click("[data-tab=data]")
            page.wait_for_selector("#tables details", timeout=60000)
            page.click("#tables details:nth-of-type(1) summary")
            page.set_viewport_size({"width": 1180, "height": 1100})
            page.screenshot(path=out / "data.png")
            browser.close()
    finally:  # never leave the example reading in the real scoreboard
        r = requests.delete(
            f"{URL}/api/observations", params={"city": CITY, "date": day.isoformat()}, timeout=30
        )
    print(f"captured 5 tabs into {out.relative_to(ROOT)}; example entry removed: {r.status_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "sprint-03"))
