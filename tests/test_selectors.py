"""Selector tests against saved AccuWeather HTML (tests/fixtures/).

If these fail after refreshing the fixtures, AccuWeather changed its layout:
update src/accuweather.py.
"""
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src import accuweather as aw
from src.capture import fmt_dates, fmt_window

FIXTURES = Path(__file__).parent / "fixtures"
JST = ZoneInfo("Asia/Tokyo")
CAPTURED_ON = date(2026, 10, 17)  # JST date the fixtures were saved


@pytest.fixture(scope="module")
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:  # browser not installed
            pytest.skip(f"Chromium unavailable: {e}")
        pg = browser.new_page()
        pg.route("**/*", lambda r: r.abort())  # offline: never hit the network
        yield pg
        browser.close()


def load(page, name):
    page.set_content((FIXTURES / name).read_text(encoding="utf-8"), wait_until="domcontentloaded")


def test_daily_cards(page):
    load(page, "daily-ueno.html")
    cards = aw.daily_cards(page, CAPTURED_ON)
    dates = [d for d, _ in cards]
    assert len(dates) >= 10
    assert dates[0] == CAPTURED_ON
    assert dates == sorted(dates) and len(set(dates)) == len(dates)
    assert date(2026, 10, 21) in dates


def test_hour_rows_day1(page):
    load(page, "hourly-ueno-day1.html")
    rows = aw.hour_rows(page, JST)
    hours = [t for t, _ in rows]
    assert hours, "no hour rows found"
    assert all(t.date() == CAPTURED_ON for t in hours)
    assert hours == sorted(hours)
    assert all(t.minute == 0 for t in hours)


def test_hour_rows_day3_full_day(page):
    load(page, "hourly-ueno-day3.html")
    hours = [t for t, _ in aw.hour_rows(page, JST)]
    assert len(hours) == 24
    assert hours[0] == datetime(2026, 10, 19, 0, tzinfo=JST)
    assert hours[-1] == datetime(2026, 10, 19, 23, tzinfo=JST)


def test_hour_row_text_matches_id(page):
    load(page, "hourly-ueno-day3.html")
    t, el = aw.hour_rows(page, JST)[6]
    assert el.query_selector(".date").inner_text().strip() == "6 AM"
    assert t.hour == 6


def test_beyond_coverage_has_no_hour_rows(page):
    load(page, "hourly-ueno-day5-redirected.html")
    assert aw.hour_rows(page, JST) == []


def test_parse_location_url():
    u = aw.parse_location_url("https://www.accuweather.com/en/jp/ueno/2409626/weather-forecast/2409626")
    assert u.key == "2409626"
    assert u.daily == "https://www.accuweather.com/en/jp/ueno/2409626/daily-weather-forecast/2409626"
    assert u.hourly(1).endswith("/hourly-weather-forecast/2409626")
    assert u.hourly(3).endswith("/hourly-weather-forecast/2409626?day=3")
    with pytest.raises(ValueError):
        aw.parse_location_url("https://www.accuweather.com/en/jp/ueno/2409626/weather-forecast/999")


def test_parse_card_date_year_rollover():
    assert aw.parse_card_date("Thu\n1/1", date(2026, 12, 28)) == date(2027, 1, 1)
    assert aw.parse_card_date("Sat 10/17", date(2026, 10, 17)) == date(2026, 10, 17)
    assert aw.parse_card_date("Today", date(2026, 10, 17)) is None


def test_is_blocked():
    assert aw.is_blocked("Access Denied", 403)
    assert aw.is_blocked("Access Denied", 200)
    assert not aw.is_blocked("Ueno, Tokyo, Japan Hourly Weather | AccuWeather", 200)


def test_note_formatting():
    assert fmt_dates([date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)]) == "Oct 28–30"
    assert fmt_dates([date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 3)]) == "Oct 31–Nov 1, Nov 3"
    s, e = datetime(2026, 10, 21, 18, tzinfo=JST), datetime(2026, 10, 22, 5, 59, tzinfo=JST)
    assert fmt_window(s, e) == "Wed Oct 21 18:00 – Thu Oct 22 05:59"
