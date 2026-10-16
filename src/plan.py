"""Turn config/trip.yaml + today's date into the list of shots to attempt.

`plan.py` only decides *what* to try. Whether AccuWeather actually covers a
date or hour is detected at run time by `capture.py`.

Usage:
    python -m src.plan                 # check the config and print today's plan
    python -m src.plan --check-active  # print active=true/false (for CI gating)
    python -m src.plan --cron          # the UTC cron line for `run_at`
"""
from __future__ import annotations

import argparse
import os
import re
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
    title: str = "Trip Weather"
    home_tz: ZoneInfo | None = None

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


class ConfigError(ValueError):
    pass


def validate_config(config: dict) -> list[str]:
    """Return human-readable problems with trip.yaml (empty list = OK)."""
    from src.accuweather import parse_location_url  # no browser needed

    errors = []
    for key in ("timezone", "day_hours", "night_hours", "locations"):
        if not config.get(key):
            errors.append(f"missing `{key}`")
    for key in ("timezone", "home_timezone"):
        if config.get(key):
            try:
                ZoneInfo(config[key])
            except Exception:
                errors.append(f"`{key}: {config[key]}` is not a valid time zone name (e.g. Europe/Paris)")
    for key in ("day_hours", "night_hours"):
        try:
            _parse_hhmm(config[key]["start"]), _parse_hhmm(config[key]["end"])
        except Exception:
            errors.append(f"`{key}` needs start/end like \"06:00\"")
    if config.get("run_at"):
        try:
            _parse_hhmm(str(config["run_at"]))
        except Exception:
            errors.append('`run_at` must look like "05:30"')
    seen = set()
    for i, loc in enumerate(config.get("locations") or []):
        name = loc.get("id") or f"location #{i + 1}"
        for key in ("id", "label", "start", "end"):
            if not loc.get(key):
                errors.append(f"{name}: missing `{key}`")
        if loc.get("id"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(loc["id"])):
                errors.append(f"{name}: `id` may only use lowercase letters, digits and dashes")
            if loc["id"] in seen:
                errors.append(f"{name}: duplicate `id`")
            seen.add(loc["id"])
        try:
            if _as_date(loc["start"]) > _as_date(loc["end"]):
                errors.append(f"{name}: `start` is after `end`")
        except Exception:
            errors.append(f"{name}: `start`/`end` must be dates like 2026-10-21")
        try:
            parse_location_url(loc.get("accuweather_url") or "")
        except ValueError:
            errors.append(f"{name}: `accuweather_url` is missing or not an AccuWeather city page "
                          "(find it with: python -m src.find_location \"City, Country\")")
    return errors


def utc_cron(config: dict, on: date | None = None) -> str:
    """Cron line (UTC) that fires at `run_at` trip-local time on date `on`."""
    tz = ZoneInfo(config["timezone"])
    local = datetime.combine(on or datetime.now(tz).date(), _parse_hhmm(str(config.get("run_at", "05:30"))), tzinfo=tz)
    utc = local.astimezone(ZoneInfo("UTC"))
    return f"{utc.minute} {utc.hour} * * *"


def build_plan(config: dict, now: datetime | None = None) -> Plan:
    tz = ZoneInfo(config["timezone"])
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
    end_date = _as_date(config["end_date"]) if config.get("end_date") else max(lp.dates[-1] for lp in locations)
    home = config.get("home_timezone")
    return Plan(tz=tz, now=now, end_date=end_date, locations=locations,
                title=config.get("title") or "Trip Weather", home_tz=ZoneInfo(home) if home else None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-active", action="store_true",
                    help="print active=true/false; also writes to $GITHUB_OUTPUT")
    ap.add_argument("--cron", action="store_true", help="print the UTC cron line for `run_at`")
    args = ap.parse_args(argv)
    config = load_config()
    errors = validate_config(config)
    if errors:
        print("config/trip.yaml has problems:\n  - " + "\n  - ".join(errors))
        return 1
    if args.cron:
        start = min(_as_date(l["start"]) for l in config["locations"])
        end = max(_as_date(l["end"]) for l in config["locations"])
        a, b = utc_cron(config, start), utc_cron(config, end)
        print(f'    - cron: "{a}"   # {config.get("run_at", "05:30")} {config["timezone"]}')
        if a != b:
            print(f"  Note: daylight saving time changes during the trip; from {end} the same "
                  f'local time is "{b}". Pick one (runs will be an hour off for part of the trip).')
        return 0
    plan = build_plan(config)
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
