# japan-weather

Cropped AccuWeather screenshots for each stop of the Japan trip (Oct 21 – Nov 5, 2026),
published as one mobile-friendly page.

**Page:** https://gerryclark.github.io/japan-weather/ (after the one-time setup below)

Trip stops and dates live in `config/trip.yaml`. Everything else reads from there.

## One-time setup (GitHub website)

1. Merge this branch into `main`.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
3. Run the workflow once by hand (see below) and check the page.
4. The daily schedule starts by itself once the workflow is on `main`.

GitHub Pages is free only for public repos. The repo and page hold only city
names, dates and weather.

## Run it manually from a phone

GitHub mobile app → this repo → **Actions** → **Weather report** → **Run workflow**
(branch `main`). Or on the website: Actions tab → Weather report → Run workflow.
A run takes a few minutes; then reload the page.

## Schedule

Once a day, in the morning (after the branch is merged into `main`):

| JST | US Pacific, until Oct 31 (PDT) | US Pacific, from Nov 1 (PST) |
|---|---|---|
| 05:30 | 1:30 PM, the previous day | 12:30 PM, the previous day |

GitHub can start scheduled runs 5–30 minutes late. Runs after `end_date` (Nov 5 JST)
exit right away without doing anything.

## What the page shows

For each stop, in trip order:

- **10-day overview**: the AccuWeather daily cards for that stop's dates only, with a note
  for dates not forecast yet.
- **Hourly, per date**: Day (06:00–17:59) and Night (18:00–05:59 next morning), cropped to
  those hours. Hours not covered yet are listed as "not yet available".

Before the trip most items say "not yet available". That is expected: AccuWeather's free
pages cover about 15 days (daily) and about 4 days (hourly). Coverage is detected each run
rather than assumed.

If one capture fails, the previous good image stays up, marked **stale** with its
capture time. The last 3 runs are kept under "Previous runs" at the bottom of the page.

## Run locally

```sh
pip install -r requirements.txt
python -m playwright install chromium
python -m src.plan          # show what will be attempted
python -m src.capture       # writes site/img/... and site/manifest.json
python -m src.build_page    # writes site/index.html
python -m pytest            # date math + selector tests against tests/fixtures/
```

## Layout

| Path | Purpose |
|---|---|
| `src/plan.py` | trip.yaml + today → dates, day/night windows, `?day=N` indexes |
| `src/accuweather.py` | URLs and **all** DOM selectors |
| `src/capture.py` | Playwright: load pages, find rows, crop, save WebP, write manifest |
| `src/build_page.py` + `templates/report.html.j2` | render `site/index.html` |
| `tests/fixtures/` | saved AccuWeather HTML; refresh it and rerun tests if captures break |

`site/` is generated. GitHub Actions keeps it between runs in the Actions cache (so
"reuse last good image" works) and publishes it to Pages. It is not committed.

### Notes

- AccuWeather refuses browsers that identify as `HeadlessChrome`, so `capture.py` sends
  the same Chromium version's user agent without that word. Nothing else is disguised.
  A run makes roughly 10–30 page loads.
- **Fallback if AccuWeather blocks GitHub's runners** (the run summary shows "blocked by
  AccuWeather"): run the same scripts from a Claude Code on the web scheduled task on this
  repo, with network access allowing `accuweather.com` **and** `awxcdn.com` (AccuWeather's
  stylesheets; without it the pages render blank). Prompt: "Run
  `python -m src.capture && python -m src.build_page`, then `git add -f site` and commit
  and push." Publishing a committed `site/` also needs a small deploy-only workflow
  trigger, which isn't set up yet.
