from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.plan import build_plan, date_range, hourly_day_index, load_config, make_window

JST = ZoneInfo("Asia/Tokyo")
DAY = {"start": "06:00", "end": "17:59"}
NIGHT = {"start": "18:00", "end": "05:59"}


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
    w = make_window(date(2026, 10, 31), NIGHT, JST)
    assert w.end.date() == date(2026, 11, 1)


def test_hourly_day_index_is_one_based_today():
    today = date(2026, 10, 17)
    assert hourly_day_index(today, today) == 1
    assert hourly_day_index(date(2026, 10, 19), today) == 3


def test_travel_days_appear_under_both_locations():
    plan = build_plan(load_config(), now=datetime(2026, 10, 17, 5, 30, tzinfo=JST))
    by_id = {lp.id: lp for lp in plan.locations}
    assert date(2026, 10, 25) in by_id["tokyo-ueno"].dates
    assert date(2026, 10, 25) in by_id["hakone"].dates
    for a, b in zip(plan.locations, plan.locations[1:]):
        assert a.dates[-1] == b.dates[0], f"{a.id} -> {b.id} should share the travel day"


def test_two_parts_per_date_in_order():
    plan = build_plan(load_config(), now=datetime(2026, 10, 17, 5, 30, tzinfo=JST))
    ueno = plan.locations[0]
    assert len(ueno.parts) == 2 * len(ueno.dates)
    assert [p.key for p in ueno.parts[:2]] == ["2026-10-21-day", "2026-10-21-night"]
    assert ueno.parts[1].image_name == "2026-10-21-night.webp"


def test_active_until_end_date_inclusive():
    cfg = load_config()
    assert build_plan(cfg, now=datetime(2026, 11, 5, 23, 0, tzinfo=JST)).active
    assert not build_plan(cfg, now=datetime(2026, 11, 6, 0, 0, tzinfo=JST)).active


def test_now_is_converted_to_jst():
    utc_evening = datetime(2026, 11, 5, 20, 30, tzinfo=ZoneInfo("UTC"))  # = Nov 6 05:30 JST
    assert not build_plan(load_config(), now=utc_evening).active


def test_every_location_has_a_url():
    for lp in build_plan(load_config()).locations:
        assert lp.url.startswith("https://www.accuweather.com/"), lp.id
