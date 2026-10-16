"""Capture cropped AccuWeather screenshots for every stop in config/trip.yaml.

Writes site/img/<location-id>/*.webp and site/manifest.json. One failed item
never fails the run: it falls back to the last good image, marked stale.

Usage: python -m src.capture
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageStat
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src import accuweather as aw
from src.plan import ROOT, HourlyPart, LocationPlan, Plan, build_plan, hourly_day_index, load_config

SITE = ROOT / "site"
MANIFEST = SITE / "manifest.json"
HISTORY = SITE / "history"
HISTORY_KEEP = 3
MAX_IMAGE_BYTES = 300_000
MAX_IMAGE_WIDTH = 1000
BLANK_STDDEV = 4  # grayscale std-dev below this = a blank/uniform image
DARK_LEVEL = 110  # luminance below this counts as text/icon ink
BLANK_DARK_FRACTION = 0.0005
CROP_ATTEMPTS = 6
VIEWPORT = {"width": 1280, "height": 2000}
NAV_RETRIES = 3

# Markers in the rendered page that history snapshots rewrite.
HISTORY_NAV_START, HISTORY_NAV_END = "<!--history-nav-->", "<!--/history-nav-->"
ARCHIVE_BANNER = "<!--archive-banner-->"


class CaptureError(Exception):
    pass


# ---------------------------------------------------------------- formatting

def fmt_dates(dates: list[date]) -> str:
    """[Oct 28, Oct 29, Oct 30, Nov 2] -> 'Oct 28–30, Nov 2'."""
    if not dates:
        return ""
    dates = sorted(dates)
    runs, start, prev = [], dates[0], dates[0]
    for d in dates[1:] + [None]:
        if d is not None and d == prev + timedelta(days=1):
            prev = d
            continue
        if start == prev:
            runs.append(f"{start:%b} {start.day}")
        elif start.month == prev.month:
            runs.append(f"{start:%b} {start.day}–{prev.day}")
        else:
            runs.append(f"{start:%b} {start.day}–{prev:%b} {prev.day}")
        if d is not None:
            start = prev = d
    return ", ".join(runs)


def fmt_window(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start:%a %b} {start.day}, {start:%H:%M}–{end:%H:%M}"
    return f"{start:%a %b} {start.day} {start:%H:%M} – {end:%a %b} {end.day} {end:%H:%M}"


def fmt_window_short(start: datetime, end: datetime) -> str:
    """'06:00–17:59' or '18:00–05:59 next day' (the date is shown in the heading)."""
    return f"{start:%H:%M}–{end:%H:%M}" + (" next day" if end.date() != start.date() else "")


# ---------------------------------------------------------------- images

def save_webp(png_segments: list[bytes], dest: Path) -> None:
    """Stack PNG segments vertically, downscale if wide, save as WebP under the size target."""
    imgs = [Image.open(io.BytesIO(b)).convert("RGB") for b in png_segments]
    width = max(i.width for i in imgs)
    canvas = Image.new("RGB", (width, sum(i.height for i in imgs)), "white")
    y = 0
    for i in imgs:
        canvas.paste(i, (0, y))
        y += i.height
    if ImageStat.Stat(canvas.convert("L")).stddev[0] < BLANK_STDDEV:
        raise CaptureError("captured image is blank (page content not painted)")
    if canvas.width > MAX_IMAGE_WIDTH:
        r = MAX_IMAGE_WIDTH / canvas.width
        canvas = canvas.resize((MAX_IMAGE_WIDTH, round(canvas.height * r)), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = b""
    for quality in (80, 70, 60, 50):
        buf = io.BytesIO()
        canvas.save(buf, "WEBP", quality=quality, method=6)
        data = buf.getvalue()
        if len(data) <= MAX_IMAGE_BYTES:
            break
    else:
        while len(data) > MAX_IMAGE_BYTES and canvas.width > 400:
            canvas = canvas.resize((int(canvas.width * 0.85), int(canvas.height * 0.85)), Image.LANCZOS)
            buf = io.BytesIO()
            canvas.save(buf, "WEBP", quality=50, method=6)
            data = buf.getvalue()
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)


# ---------------------------------------------------------------- browser

def new_context(browser, block_hosts: bool | None = None):
    # AccuWeather (Akamai) refuses the "HeadlessChrome" user agent token, so
    # present the same browser version as regular Chrome. Nothing else is changed.
    probe = browser.new_page()
    ua = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
    probe.close()
    ctx = browser.new_context(viewport=VIEWPORT, locale="en-US", timezone_id="Asia/Tokyo", user_agent=ua)

    def route(r):
        host = urlparse(r.request.url).hostname or ""
        if any(p in host for p in aw.BLOCKED_HOST_PATTERNS):
            return r.abort()
        return r.continue_()

    if block_hosts is None:
        block_hosts = os.environ.get("AW_BLOCK_HOSTS", "1") != "0"
    if block_hosts:
        ctx.route("**/*", route)
    return ctx


def open_page(page, url: str) -> None:
    """Navigate with retries; raise CaptureError if blocked or unreachable."""
    last = None
    for attempt in range(NAV_RETRIES):
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("load", timeout=15_000)
            except PlaywrightError:
                pass  # some third-party request is slow; content is already there
            status = resp.status if resp else None
            if aw.is_blocked(page.title(), status):
                last = CaptureError(f"blocked by AccuWeather (HTTP {status}, '{page.title()}')")
            elif status and status >= 400:
                last = CaptureError(f"HTTP {status}")
            else:
                prepare_page(page)
                return
        except PlaywrightError as e:
            last = CaptureError(f"navigation failed: {str(e).splitlines()[0]}")
        time.sleep(2 + 3 * attempt)
    raise last


def prepare_page(page) -> None:
    """Dismiss consent prompts, hide ads and anything fixed/sticky over the content."""
    for btn in page.query_selector_all("button, a[role=button]"):
        try:
            if btn.is_visible() and aw.DISMISS_BUTTON_TEXT.match((btn.inner_text() or "").strip()):
                btn.click(timeout=2000)
        except PlaywrightError:
            pass
    page.add_style_tag(content=aw.HIDE_CSS)
    page.evaluate("""() => {
        for (const el of document.querySelectorAll('body *')) {
            const p = getComputedStyle(el).position;
            if (p === 'fixed' || p === 'sticky') el.style.setProperty('display', 'none', 'important');
        }
    }""")
    page.wait_for_timeout(500)


def is_blank(png: bytes) -> bool:
    """True for a crop with no dark pixels: empty, or AccuWeather's grey loading skeleton."""
    gray = Image.open(io.BytesIO(png)).convert("L")
    gray.thumbnail((400, 4000))
    hist = gray.histogram()
    dark = sum(hist[:DARK_LEVEL])
    return dark < BLANK_DARK_FRACTION * gray.width * gray.height


def crop_png(page, elements) -> bytes:
    """Screenshot the union bounding box of `elements` (page coordinates).

    AccuWeather paints grey placeholders until its scripts hydrate each block
    (often when it scrolls into view), so scroll through the elements and retry
    until the crop has real content.
    """
    for attempt in range(CROP_ATTEMPTS):
        for el in (elements[0], elements[-1], elements[0]):
            el.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(300)
        boxes = [el.evaluate("""e => { const r = e.getBoundingClientRect();
            return [r.left + scrollX, r.top + scrollY, r.right + scrollX, r.bottom + scrollY]; }""")
            for el in elements]
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        if x1 - x0 < 50 or y1 - y0 < 20:
            raise CaptureError("page layout did not render (stylesheets blocked?)")
        pad = 4
        clip = {"x": max(0, x0 - pad), "y": max(0, y0 - pad), "width": x1 - x0 + 2 * pad, "height": y1 - y0 + 2 * pad}
        png = page.screenshot(clip=clip, full_page=True, type="png", animations="disabled")
        if not is_blank(png):
            return png
        page.wait_for_timeout(1500)
    raise CaptureError("forecast content never painted (only loading placeholders)")


# ---------------------------------------------------------------- manifest helpers

def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        return {}


def previous_entries(prev: dict) -> dict:
    """{(location_id, item_key): entry} from the previous manifest."""
    out = {}
    for loc in prev.get("locations", []):
        out[(loc["id"], "overview")] = loc.get("overview", {})
        for p in loc.get("parts", []):
            out[(loc["id"], p["key"])] = p
    return out


def fallback(prev_entry: dict | None, base: dict, reason: str) -> dict:
    """Reuse the last good image (marked stale) or report the error."""
    entry = dict(base)
    if prev_entry and prev_entry.get("image") and (SITE / prev_entry["image"]).exists():
        entry.update(status="stale", image=prev_entry["image"], captured_at=prev_entry.get("captured_at"),
                     note=f"Showing last good image. Latest attempt failed: {reason}")
    else:
        entry.update(status="error", image=None, captured_at=None, note=f"Capture failed: {reason}")
    return entry


def snapshot_history(prev: dict) -> None:
    """Copy the previous run's page + images into site/history/<stamp>/."""
    index = SITE / "index.html"
    if not prev.get("generated_at") or not index.exists():
        return
    stamp = datetime.fromisoformat(prev["generated_at"]).strftime("%Y%m%d-%H%M")
    dest = HISTORY / stamp
    if dest.exists():
        return
    dest.mkdir(parents=True)
    html = index.read_text(encoding="utf-8")
    a, b = html.find(HISTORY_NAV_START), html.find(HISTORY_NAV_END)
    if a != -1 and b != -1:
        html = html[:a] + '<a href="../../index.html">← Back to the latest report</a>' + html[b + len(HISTORY_NAV_END):]
    html = html.replace(ARCHIVE_BANNER, '<p class="archive">Archived copy of an earlier run.</p>')
    (dest / "index.html").write_text(html, encoding="utf-8")
    shutil.copy2(MANIFEST, dest / "manifest.json")
    if (SITE / "img").exists():
        shutil.copytree(SITE / "img", dest / "img")
    for old in sorted(p for p in HISTORY.iterdir() if p.is_dir())[:-HISTORY_KEEP]:
        shutil.rmtree(old)


# ---------------------------------------------------------------- capture

def capture_overview(page, lp: LocationPlan, plan: Plan, urls: aw.LocationUrls, prev_entry) -> dict:
    today = plan.now.date()
    future = [d for d in lp.dates if d >= today]
    base = {"total": len(lp.dates), "found": 0, "dates_missing": []}
    if not future:
        if prev_entry and prev_entry.get("image"):
            return {**prev_entry, "status": "past", "note": "These dates have passed; last forecast captured is shown."}
        return {**base, "status": "past", "image": None, "captured_at": None, "note": "These dates have passed."}
    try:
        open_page(page, urls.daily)
        cards = dict(aw.daily_cards(page, today))
        if not cards:
            raise CaptureError("no day cards found on the daily page (layout change?)")
        found = [d for d in future if d in cards]
        missing = [d for d in future if d not in cards]
        entry = {**base, "found": len(found), "dates_missing": [d.isoformat() for d in missing],
                 "captured_at": plan.now.isoformat()}
        note = f"Forecast not yet available for {fmt_dates(missing)}." if missing else ""
        if not found:
            return {**entry, "status": "unavailable", "image": None, "captured_at": None, "note": note}
        rel = f"img/{lp.id}/overview.webp"
        save_webp([crop_png(page, [cards[d] for d in found])], SITE / rel)
        return {**entry, "status": "partial" if missing else "ok", "image": rel, "note": note}
    except (CaptureError, PlaywrightError, OSError) as e:
        print(f"  ! overview: {e}")
        return fallback(prev_entry, base, str(e).splitlines()[0])


def capture_hourly(page, lp: LocationPlan, plan: Plan, urls: aw.LocationUrls, prev: dict) -> list[dict]:
    today = plan.now.date()
    current_hour = plan.now.replace(minute=0, second=0, microsecond=0)
    # Per part: hours still to come, segments captured, hours found, error.
    state = {}
    needed_days: set[int] = set()
    for p in lp.parts:
        future = [h for h in p.window.hours() if h >= current_hour]
        state[p.key] = {"future": future, "segments": [], "found": set(), "error": None}
        needed_days |= {hourly_day_index(h.date(), today) for h in future}

    coverage_end = None  # first day index AccuWeather does not cover
    for day in sorted(d for d in needed_days if d >= 1):
        affected = [p for p in lp.parts if any(hourly_day_index(h.date(), today) == day for h in state[p.key]["future"])]
        try:
            open_page(page, urls.hourly(day))
            rows = dict(aw.hour_rows(page, plan.tz))
            if not rows:
                if not aw.is_hourly_url(page.url) or day > 1:
                    coverage_end = day
                    print(f"  hourly coverage ends before day={day}")
                    break
                raise CaptureError("no hour rows on the hourly page (layout change?)")
            for p in affected:
                st = state[p.key]
                hit = [h for h in st["future"] if h in rows and hourly_day_index(h.date(), today) == day]
                if hit:
                    st["segments"].append(crop_png(page, [rows[h] for h in hit]))
                    st["found"].update(hit)
        except (CaptureError, PlaywrightError, OSError) as e:
            msg = str(e).splitlines()[0]
            print(f"  ! hourly day={day}: {msg}")
            for p in affected:
                state[p.key]["error"] = state[p.key]["error"] or msg

    results = []
    for p in lp.parts:
        st = state[p.key]
        label = fmt_window(p.window.start, p.window.end)
        base = {"key": p.key, "date": p.date.isoformat(), "kind": p.kind, "window": label,
                "window_short": fmt_window_short(p.window.start, p.window.end),
                "total_hours": len(p.window.hours())}
        prev_entry = prev.get((lp.id, p.key))
        if not st["future"]:
            if prev_entry and prev_entry.get("image"):
                results.append({**prev_entry, **base, "status": "past", "note": "This window has passed; last forecast captured is shown."})
            else:
                results.append({**base, "status": "past", "image": None, "captured_at": None, "note": "This window has passed."})
            continue
        if st["error"]:
            results.append(fallback(prev_entry, base, st["error"]))
            continue
        missing = [h for h in st["future"] if h not in st["found"]]
        note = ""
        if missing:
            note = f"Hourly forecast not yet available for {fmt_window(missing[0], missing[-1] + timedelta(minutes=59))}."
        if not st["segments"]:
            results.append({**base, "status": "unavailable", "image": None, "captured_at": None,
                            "found_hours": 0, "note": note})
            continue
        rel = f"img/{lp.id}/{p.image_name}"
        try:
            save_webp(st["segments"], SITE / rel)
        except (CaptureError, OSError) as e:
            results.append(fallback(prev_entry, base, str(e)))
            continue
        results.append({**base, "status": "partial" if missing else "ok", "image": rel,
                        "captured_at": plan.now.isoformat(), "found_hours": len(st["found"]), "note": note})
    if coverage_end:
        print(f"  hourly coverage: through day={coverage_end - 1}")
    return results


def capture_location(ctx, lp: LocationPlan, plan: Plan, prev: dict) -> dict:
    print(f"== {lp.label} [{lp.id}]")
    out = {"id": lp.id, "label": lp.label, "url": lp.url,
           "dates": [d.isoformat() for d in lp.dates]}
    try:
        urls = aw.parse_location_url(lp.url)
    except ValueError as e:
        reason = str(e)
        out["overview"] = fallback(prev.get((lp.id, "overview")), {"total": len(lp.dates), "found": 0}, reason)
        out["parts"] = [fallback(prev.get((lp.id, p.key)), {"key": p.key, "date": p.date.isoformat(), "kind": p.kind,
                                 "window": fmt_window(p.window.start, p.window.end)}, reason) for p in lp.parts]
        return out
    page = ctx.new_page()
    try:
        out["overview"] = capture_overview(page, lp, plan, urls, prev.get((lp.id, "overview")))
        print(f"  overview: {out['overview']['status']} {out['overview'].get('note', '')}")
        out["parts"] = capture_hourly(page, lp, plan, urls, prev)
        for r in out["parts"]:
            print(f"  {r['key']:<16} {r['status']:<11} {r.get('note', '')}")
    finally:
        page.close()
    return out


def main() -> int:
    plan = build_plan(load_config())
    if not plan.active:
        print(f"Today ({plan.now.date()}) is after end_date ({plan.end_date}); nothing to capture.")
        return 0
    SITE.mkdir(exist_ok=True)
    prev_manifest = load_manifest()
    snapshot_history(prev_manifest)
    prev = previous_entries(prev_manifest)

    locations = []
    with sync_playwright() as pw:
        try:
            # Full Chromium (new headless); the slim headless shell is refused by AccuWeather.
            browser = pw.chromium.launch(channel="chromium")
        except PlaywrightError:
            browser = pw.chromium.launch()
        ctx = new_context(browser)
        for lp in plan.locations:
            try:
                locations.append(capture_location(ctx, lp, plan, prev))
            except Exception as e:  # never let one location sink the run
                print(f"  ! {lp.id}: unexpected error: {e!r}")
                locations.append({"id": lp.id, "label": lp.label, "url": lp.url,
                                  "dates": [d.isoformat() for d in lp.dates],
                                  "overview": fallback(prev.get((lp.id, "overview")), {"total": len(lp.dates), "found": 0}, repr(e)),
                                  "parts": [fallback(prev.get((lp.id, p.key)), {"key": p.key, "date": p.date.isoformat(),
                                            "kind": p.kind, "window": fmt_window(p.window.start, p.window.end)}, repr(e))
                                            for p in lp.parts]})
        browser.close()

    manifest = {"generated_at": plan.now.isoformat(), "timezone": str(plan.tz), "locations": locations}
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    tmp.replace(MANIFEST)

    items = [l["overview"] for l in locations] + [p for l in locations for p in l["parts"]]
    failed = sum(i["status"] in ("error", "stale") for i in items)
    if failed:
        print(f"::warning::{failed} of {len(items)} items failed this run (see manifest.json notes)")
    print(f"Wrote {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
