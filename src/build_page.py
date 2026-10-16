"""Render site/index.html from site/manifest.json.

Usage: python -m src.build_page
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.capture import ARCHIVE_BANNER, HISTORY, HISTORY_NAV_END, HISTORY_NAV_START, MANIFEST, SITE
from src.plan import ROOT, load_config


STATUS_LABEL = {
    "ok": "",
    "partial": "partial",
    "unavailable": "not yet available",
    "stale": "stale",
    "error": "failed",
    "past": "past",
}


def fmt_ts(iso: str | None, tz: ZoneInfo | None = None) -> str:
    """24h time in `tz` (default: the time zone the timestamp was written in)."""
    if not iso:
        return ""
    t = datetime.fromisoformat(iso)
    t = t.astimezone(tz) if tz else t
    return f"{t:%a %b} {t.day}, {t:%H:%M} {t.tzname()}"


def fmt_ts_12h(iso: str, tz: ZoneInfo) -> str:
    t = datetime.fromisoformat(iso).astimezone(tz)
    return f"{t:%a %b} {t.day}, {t.strftime('%I:%M %p').lstrip('0')} {t.tzname()}"


def cache_bust(entry: dict) -> str:
    """Image URL with ?v=<captured time> so phones don't show a cached old image."""
    v = (entry.get("captured_at") or "").replace(":", "").replace("-", "")[:13]
    return f"{entry['image']}?v={v}" if v else entry["image"]


def summarize(loc: dict) -> str:
    ov = loc.get("overview", {})
    parts = loc.get("parts", [])
    ok = sum(p["status"] == "ok" for p in parts)
    partial = sum(p["status"] == "partial" for p in parts)
    s = f"overview {ov.get('found', 0)}/{ov.get('total', len(loc.get('dates', [])))} days, hourly {ok}/{len(parts)} parts"
    if partial:
        s += f" (+{partial} partial)"
    stale = sum(p["status"] in ("stale", "error") for p in parts) + (ov.get("status") in ("stale", "error"))
    if stale:
        s += f", {stale} failed"
    return s


def group_parts(loc: dict) -> list[dict]:
    """[{date, label, parts:[day, night]}] in date order."""
    by_date: dict[str, list] = {}
    for p in loc.get("parts", []):
        by_date.setdefault(p["date"], []).append(p)
    out = []
    for d, parts in sorted(by_date.items()):
        dd = date.fromisoformat(d)
        out.append({"date": d, "label": f"{dd:%a %b} {dd.day}",
                    "parts": sorted(parts, key=lambda p: p["kind"] != "day")})
    return out


def render(manifest: dict, config: dict | None = None) -> str:
    config = config or {}
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "j2"]))
    env.filters["ts"] = fmt_ts
    env.filters["bust"] = cache_bust
    history = sorted((p.name for p in HISTORY.iterdir() if p.is_dir()), reverse=True) if HISTORY.exists() else []
    generated = manifest.get("generated_at")
    trip_tz = ZoneInfo(manifest.get("timezone") or config.get("timezone") or "UTC")
    home_name = config.get("home_timezone") or manifest.get("home_timezone")
    home_tz = ZoneInfo(home_name) if home_name else None
    trip_tz_label = datetime.now(trip_tz).tzname()
    return env.get_template("report.html.j2").render(
        manifest=manifest,
        locations=manifest.get("locations", []),
        title=config.get("title") or manifest.get("title") or "Trip Weather",
        updated_local=fmt_ts(generated, trip_tz) if generated else "never",
        updated_home=fmt_ts_12h(generated, home_tz) if generated and home_tz else "",
        trip_tz_label=trip_tz_label,
        summarize=summarize,
        group_parts=group_parts,
        status_label=STATUS_LABEL,
        history=history,
        history_nav_start=HISTORY_NAV_START,
        history_nav_end=HISTORY_NAV_END,
        archive_banner=ARCHIVE_BANNER,
    )


def main() -> int:
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, ValueError) as e:
        print(f"No usable {MANIFEST.relative_to(ROOT)} ({e}); rendering an empty page.")
        manifest = {}
    SITE.mkdir(exist_ok=True)
    out = SITE / "index.html"
    try:
        config = load_config()
    except OSError:
        config = {}
    out.write_text(render(manifest, config), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
