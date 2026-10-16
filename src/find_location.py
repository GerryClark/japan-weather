"""Find the AccuWeather city page (`accuweather_url`) for a place.

Usage:
    python -m src.find_location "Kyoto, Japan"
    python -m src.find_location "Trastevere, Rome" --max 8

Searches AccuWeather, follows each result to its real city page and prints the
name AccuWeather shows plus the URL to paste into config/trip.yaml. Pick the
result whose name and region match; neighbourhood-level results ("Place") are
often closer to a hotel than the whole city ("Locality").
"""
from __future__ import annotations

import argparse
import sys
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.accuweather import BASE
from src.capture import CaptureError, new_context, open_page

SEARCH_RESULT = ".locations-list a[href*='three-day-redirect']"
PAGE_HEADING = "h1, .header-loc"


def canonical(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help='e.g. "Kyoto, Japan" or "Shinjuku, Tokyo"')
    ap.add_argument("--max", type=int, default=6, help="how many results to resolve")
    args = ap.parse_args()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chromium")
        except PlaywrightError:
            browser = pw.chromium.launch()
        page = new_context(browser).new_page()
        try:
            open_page(page, f"{BASE}/en/search-locations?query={quote(args.query)}")
        except CaptureError as e:
            print(f"Search failed: {e}")
            return 1

        if "/weather-forecast/" in page.url:  # AccuWeather jumped straight to one match
            results = [(args.query, page.url)]
        else:
            results = []
            for a in page.query_selector_all(SEARCH_RESULT):
                label = " ".join(a.inner_text().split())
                href = a.get_attribute("href") or ""
                if label and href and "key=GEO_" in href:
                    results.append((label, BASE + href))
            results = results[: args.max]
        if not results:
            print("No matches. Try a different spelling, the city instead of a district, or add the country.")
            return 1

        print(f'Results for "{args.query}":\n')
        for i, (label, href) in enumerate(results, 1):
            try:
                open_page(page, href)
                heading = page.query_selector(PAGE_HEADING)
                name = " ".join(heading.inner_text().split()) if heading else "?"
                ok = "/weather-forecast/" in page.url
                print(f"{i}. {label}\n   AccuWeather name: {name}")
                print(f"   accuweather_url: \"{canonical(page.url)}\"" if ok else f"   (could not resolve: {page.url})")
            except (CaptureError, PlaywrightError) as e:
                print(f"{i}. {label}\n   (could not open: {str(e).splitlines()[0]})")
            print()
        browser.close()
    print("Copy the matching accuweather_url into config/trip.yaml, then run: python -m src.plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
