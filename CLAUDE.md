# Japan Trip Weather Report

## Goal
Build and maintain a tool that captures AccuWeather screenshots for each stop of
a Japan trip (Oct 21 – Nov 5, 2026) and publishes them as **one combined web page**.
It must run **in the cloud on a schedule** (the owner will be traveling, away from
their computer) and also be **runnable manually on demand**, ideally from a phone.

Trip locations and dates live in `config/trip.yaml`. That file is the single
source of truth. Never hard-code dates or cities in scripts.

## What each run produces

For every location in `config/trip.yaml`, in trip order:

1. **10-day overview.** Screenshot of the AccuWeather daily forecast
   (`/daily-weather-forecast/`), **cropped to only the rows/cards for that
   location's dates**. If some of the location's dates are beyond the forecast
   range, show the dates that are available and add a note listing the missing
   dates: "Forecast not yet available for Oct 28–30."
   If none are available, show the note only (no screenshot).

2. **Hourly detail, per date, in two parts.** For each date at that location:
   - **Day:** 06:00–17:59 JST
   - **Night:** 18:00 that date to 05:59 the next morning JST
   Each part is its own cropped screenshot of the AccuWeather hourly forecast
   (`/hourly-weather-forecast/`, which uses a `?day=N` query parameter).
   Crop to only the hours in that window. If any hours in the window are not
   covered yet, show what exists and say "Hourly forecast not yet available for
   <window>". If none are covered, show the message only.
   Hour windows come from `day_hours` / `night_hours` in the config.

Travel days (e.g., Oct 25) appear under both locations. That is intended.

### Combined page
- One static `index.html` in `site/`, grouped by location, then by date.
- A header showing "Last updated: <timestamp JST and US Pacific>" plus a
  summary line per location (e.g., "Tokyo – Ueno: overview 5/5 days, hourly 0/10 parts").
- A jump menu to each location. Mobile-friendly: the owner will read this on a
  phone in Japan. Images should be `loading="lazy"`, scale to width, and be
  compressed (WebP or optimized PNG/JPEG, target under 300 KB each).
- Keep a small `site/history/` of the previous few runs' pages, or at least the
  previous run, so a bad scrape does not wipe out the last good images.
  If a capture fails for one item, reuse the last good image and mark it
  "stale, captured <time>". Never fail the whole run because one item failed.

## Architecture

```
japan-weather/
├── CLAUDE.md                     # this file
├── README.md                     # how to run manually / trigger from phone
├── config/
│   └── trip.yaml                 # locations, dates, hour windows, end_date
├── src/
│   ├── capture.py                # Playwright: open pages, find rows, crop screenshots
│   ├── accuweather.py            # URL building + DOM selectors (keep all selectors here)
│   ├── plan.py                   # turns trip.yaml + today's date into a list of shots
│   └── build_page.py             # renders site/index.html from manifest.json
├── templates/
│   └── report.html.j2            # Jinja2 template for the combined page
├── site/                         # published output (GitHub Pages)
│   ├── index.html
│   ├── manifest.json             # what was captured, when, status per item
│   ├── img/<location-id>/...     # overview.webp, 2026-10-21-day.webp, ...-night.webp
│   └── history/
├── tests/
│   ├── test_plan.py              # date math, night window wrap, travel-day overlap
│   └── fixtures/                 # saved AccuWeather HTML for offline selector tests
├── requirements.txt              # playwright, pyyaml, jinja2, pillow
└── .github/workflows/weather.yml
```

Stack: Python 3.11+, Playwright (Chromium), Jinja2, Pillow. Keep it simple; no
framework.

### Cropping approach
Prefer **element screenshots** over pixel math: locate the DOM element for each
matching day row or hour row, compute the union bounding box of the first and
last matching elements, and screenshot that clip region (`page.screenshot(clip=...)`).
Read dates/hours from the DOM text, not from position, and parse them in
Asia/Tokyo time. Dismiss cookie/consent banners and ads overlays before capturing.
Use a fixed viewport (e.g., 1280×2000) and `locale="en-US"`, `timezone_id="Asia/Tokyo"`.

### Forecast availability
Do not assume coverage limits. Detect them at run time from what the page
actually lists (AccuWeather's free daily view has been about 10 days and hourly
about 72 hours, but this changes). `plan.py` decides what to attempt;
`capture.py` reports what was really found.

## Scheduling & manual runs

**Primary: GitHub Actions** (`.github/workflows/weather.yml`)
- `on.schedule`: daily at 05:30 JST (`30 20 * * *` UTC). Add a second run at
  17:30 JST (`30 8 * * *` UTC) during the trip if useful.
- `on.workflow_dispatch`: manual run. The owner can trigger it from the GitHub
  website or the GitHub mobile app (Actions → workflow → "Run workflow").
- Steps: checkout → set up Python → `pip install -r requirements.txt` →
  `playwright install --with-deps chromium` → `python -m src.capture` →
  `python -m src.build_page` → deploy `site/` to GitHub Pages
  (`actions/upload-pages-artifact` + `actions/deploy-pages`).
- Exit early (success, no-op) once today (JST) is after `end_date`.
- Commit `site/manifest.json` + images back, or keep the last good images in an
  Actions cache, so "reuse last good image" works across runs.

**Fallback if AccuWeather blocks GitHub runner IPs** (403, captcha, empty page):
run the same scripts from a **Claude Code on the web scheduled task** on this
repo, with that environment's network access set to allow `accuweather.com`.
The task's prompt is: "Run `python -m src.capture && python -m src.build_page`,
commit and push `site/`." It can also be started manually with "Run now".
Document whichever one works in README.md.

Do not use any API key or paid AccuWeather API unless the owner approves it.

## Privacy
The published page and repo contain **weather only**: city labels and dates.
Do not commit hotel names, addresses, booking numbers, seat numbers, flight
numbers or phone numbers. If Pages must be public (free plan), keep it that way.
Otherwise use a private repo with Pages (paid plan) or an unguessable path.

## Working rules for Claude Code
- First task: look up and verify each location's AccuWeather URL / location key
  and fill `accuweather_url` in `config/trip.yaml`. Show them to the owner.
- Save real AccuWeather HTML into `tests/fixtures/` early and write selector
  tests against it, so layout changes are caught quickly.
- Run the full pipeline locally once and show the owner `site/index.html`
  (screenshot or the Pages URL) before enabling the schedule.
- Remember: today is before the trip, so most items will legitimately show
  "not yet available". That is correct output, not a bug.
- After the setup works, give the owner: the Pages URL, how to trigger a manual
  run from the phone, and when the schedule runs in both JST and Pacific time.
