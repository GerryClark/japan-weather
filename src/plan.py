"""Turn config/trip.yaml + today's date into the list of shots to attempt.

`plan.py` only decides *what* to try. Whether AccuWeather actually covers a
date or hour is detected at run time by `capture.py`.

Usage:
    python -m src.plan                 # print the plan for today (JST)
    python -m src.plan --check-active  # print active=true/false (for CI gating)
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "trip.yaml"


@dataclass(frozen=True)
class HourWindow:
    """A half-open-by-the-minute window of whole hours, e.g. 18:00–05:59."""

    start: datetime  # first hour included (tz-aware)
    end: datetime  # last minute included (tz-aware), e.g. 05:59 next day

    def hours(self) -> list[datetime]:
        """Every top-of-hour timestamp inside the window."""
        out, t = [], self.start
        while t <= self.end:
            out.append(t)
            t += timedelta(hours=1)
        return out

    def contains(self, t: datetime) -> bool:
        return self.start <= t <= self.end


@dataclass
class HourlyPart:
    location_id: str
    date: date
    kind: str  # "day" | "night"
    window: HourWindow

    @property
    def key(self) -> str:
        return f"{self.date.isoformat()}-{self.kind}"

    @property
    def image_name(self) -> str:
        return f"{self.key}.webp"


@dataclass
class LocationPlan:
    id: str
    label: str
    url: str
    dates: list[date]
    parts: list[HourlyPart] = field(default_factory=list)


@dataclass
class Plan:
    tz: ZoneInfo
    now: datetime
    end_date: date
    locations: list[LocationPlan]

    @property
    def active(self) -> bool:
        return self.now.date() <= self.end_date


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from start to end."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def make_window(d: date, spec: dict, tz: ZoneInfo) -> HourWindow:
    """Build a window anchored on date `d`. If end <= start it wraps to d+1."""
    start_t, end_t = _parse_hhmm(spec["start"]), _parse_hhmm(spec["end"])
    start = datetime.combine(d, start_t, tzinfo=tz)
    end_day = d + timedelta(days=1) if end_t <= start_t else d
    end = datetime.combine(end_day, end_t, tzinfo=tz)
    return HourWindow(start, end)


def hourly_day_index(target: date, today: date) -> int:
    """AccuWeather's hourly `?day=N`: 1 is today (in the location's time zone)."""
    return (target - today).days + 1


def build_plan(config: dict, now: datetime | None = None) -> Plan:
    tz = ZoneInfo(config.get("timezone", "Asia/Tokyo"))
    now = (now or datetime.now(tz)).astimezone(tz)
    locations = []
    for loc in config["locations"]:
        dates = date_range(_as_date(loc["start"]), _as_date(loc["end"]))
        lp = LocationPlan(
            id=loc["id"],
            label=loc["label"],
            url=loc.get("accuweather_url") or "",
            dates=dates,
        )
        for d in dates:
            lp.parts.append(HourlyPart(lp.id, d, "day", make_window(d, config["day_hours"], tz)))
            lp.parts.append(HourlyPart(lp.id, d, "night", make_window(d, config["night_hours"], tz)))
        locations.append(lp)
    return Plan(tz=tz, now=now, end_date=_as_date(config["end_date"]), locations=locations)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-active", action="store_true",
                    help="print active=true/false; also writes to $GITHUB_OUTPUT")
    args = ap.parse_args(argv)
    plan = build_plan(load_config())
    if args.check_active:
        line = f"active={'true' if plan.active else 'false'}"
        print(line)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(line + "\n")
        if not plan.active:
            print(f"Today ({plan.now.date()}) is after end_date ({plan.end_date}); nothing to do.")
        return 0
    print(f"now: {plan.now:%Y-%m-%d %H:%M %Z}  active: {plan.active}")
    for lp in plan.locations:
        print(f"{lp.label} [{lp.id}] {lp.dates[0]}..{lp.dates[-1]}  {lp.url or '(no url)'}")
        for p in lp.parts:
            print(f"   {p.key:<16} {p.window.start:%m-%d %H:%M} -> {p.window.end:%m-%d %H:%M}"
                  f"  day={hourly_day_index(p.window.start.date(), plan.now.date())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
