"""Date math and config handling. Uses a sample trip so the tests don't depend
on whatever trip is currently in config/trip.yaml (except the last test)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.plan import build_plan, date_range, hourly_day_index, load_config, make_window, utc_cron, validate_config

JST = ZoneInfo("Asia/Tokyo")
DAY = {"start": "06:00", "end": "17:59"}
NIGHT = {"start": "18:00", "end": "05:59"}
URL = "https://www.accuweather.com/en/jp/ueno/2409626/weather-forecast/2409626"


def sample_config(**overrides):
    cfg = {
        "title": "Sample Trip",
        "timezone": "Asia/Tokyo",
        "day_hours": DAY,
        "night_hours": NIGHT,
        "end_date": date(2026, 11, 5),
        "locations": [
            {"id": "a", "label": "A", "accuweather_url": URL, "start": date(2026, 10, 21), "end": date(2026, 10, 25)},
            {"id": "b", "label": "B", "accuweather_url": URL, "start": date(2026, 10, 25), "end": date(2026, 11, 5)},
        ],
    }
    cfg.update(overrides)
    return cfg


def test_date_range_inclusive():
    assert date_range(date(2026, 10, 21), date(2026, 10, 25)) == [date(2026, 10, d) for d in range(21, 26)]


def test_day_window():
    w = make_window(date(2026, 10, 21), DAY, JST)
    assert w.start == datetime(2026, 10, 21, 6, 0, tzinfo=JST)
    assert w.end == datetime(2026, 10, 21, 17, 59, tzinfo=JST)
    hours = w.hours()
    assert len(hours) == 12 and hours[0].hour == 6 and hours[-1].hour == 17


def test_night_window_wraps_past_midnight():
    w = make_window(date(2026, 10, 21), NIGHT, JST)
    assert w.start == datetime(2026, 10, 21, 18, 0, tzinfo=JST)
    assert w.end == datetime(2026, 10, 22, 5, 59, tzinfo=JST)
    hours = w.hours()
    assert len(hours) == 12
    assert hours[0] == datetime(2026, 10, 21, 18, tzinfo=JST)
    assert hours[-1] == datetime(2026, 10, 22, 5, tzinfo=JST)
    assert w.contains(datetime(2026, 10, 22, 0, 30, tzinfo=JST))


def test_night_window_crosses_month_end():
    assert make_window(date(2026, 10, 31), NIGHT, JST).end.date() == date(2026, 11, 1)


def test_hourly_day_index_is_one_based_today():
    today = date(2026, 10, 17)
    assert hourly_day_index(today, today) == 1
    assert hourly_day_index(date(2026, 10, 19), today) == 3


def test_travel_day_appears_under_both_locations():
    plan = build_plan(sample_config(), now=datetime(2026, 10, 17, 5, 30, tzinfo=JST))
    a, b = plan.locations
    assert date(2026, 10, 25) in a.dates and date(2026, 10, 25) in b.dates


def test_two_parts_per_date_in_order():
    a = build_plan(sample_config(), now=datetime(2026, 10, 17, 5, 30, tzinfo=JST)).locations[0]
    assert len(a.parts) == 2 * len(a.dates)
    assert [p.key for p in a.parts[:2]] == ["2026-10-21-day", "2026-10-21-night"]
    assert a.parts[1].image_name == "2026-10-21-night.webp"


def test_active_until_end_date_inclusive():
    cfg = sample_config()
    assert build_plan(cfg, now=datetime(2026, 11, 5, 23, 0, tzinfo=JST)).active
    assert not build_plan(cfg, now=datetime(2026, 11, 6, 0, 0, tzinfo=JST)).active


def test_now_is_converted_to_trip_time_zone():
    utc_evening = datetime(2026, 11, 5, 20, 30, tzinfo=ZoneInfo("UTC"))  # = Nov 6 05:30 JST
    assert not build_plan(sample_config(), now=utc_evening).active


def test_end_date_defaults_to_last_location():
    cfg = sample_config()
    del cfg["end_date"]
    assert build_plan(cfg).end_date == date(2026, 11, 5)


def test_other_time_zone_trip():
    cfg = sample_config(timezone="Europe/Rome")
    plan = build_plan(cfg, now=datetime(2026, 10, 21, 12, tzinfo=ZoneInfo("UTC")))
    assert plan.locations[0].parts[0].window.start == datetime(2026, 10, 21, 6, tzinfo=ZoneInfo("Europe/Rome"))


def test_utc_cron():
    assert utc_cron(sample_config(run_at="05:30"), date(2026, 10, 21)) == "30 20 * * *"
    # Rome: CEST (UTC+2) before Oct 25, CET (UTC+1) after
    rome = sample_config(timezone="Europe/Rome", run_at="07:00")
    assert utc_cron(rome, date(2026, 10, 21)) == "0 5 * * *"
    assert utc_cron(rome, date(2026, 11, 1)) == "0 6 * * *"


def test_validate_config_reports_problems():
    assert validate_config(sample_config()) == []
    bad = sample_config(timezone="Mars/Olympus")
    bad["locations"][1].update(id="a", accuweather_url="", start=date(2026, 11, 9))
    errors = "\n".join(validate_config(bad))
    assert "time zone" in errors
    assert "duplicate" in errors
    assert "accuweather_url" in errors
    assert "after `end`" in errors


def test_current_trip_config_is_valid():
    assert validate_config(load_config()) == []
