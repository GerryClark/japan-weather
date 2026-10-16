# Start guide

## Every day on the trip

**Open the page:** https://gerryclark.github.io/japan-weather/
(Bookmark it or add it to your phone's home screen.)

It updates by itself every morning at 05:30 local trip time. The top of the page
shows when it last updated, in trip time and US Pacific time.

- Tap a city in the row of buttons to jump to it.
- Each city has a **10-day overview**, then a **Day** (06:00–17:59) and
  **Night** (18:00–05:59) hourly forecast for each date you're there.
- Labels:
  - **not yet available**: too far ahead. AccuWeather's hourly forecast covers
    only about 4 days, so this is normal until a few days before.
  - **partial**: some of those hours or dates are covered so far.
  - **stale**: that day's capture failed, so you're seeing the previous image
    (its capture time is shown).
  - **past**: the date is over.
- **Previous runs** at the bottom keeps the last 3 versions.

## Update it right now

GitHub app → **japan-weather** → **Actions** → **Weather report** →
**Run workflow** → **Run workflow**. Wait about 2 minutes, then reload the page.

## If something looks wrong

- **Page didn't update:** in the GitHub app, open Actions → Weather report and
  tap the latest run. A red ✗ means it failed; the step summary says why.
- **Many items say "stale" or "failed":** AccuWeather may be blocking GitHub or
  have changed its page layout. Ask Claude Code to "check the latest Weather
  report run and fix it".

The runs stop by themselves after the trip's last day.

---

## Setting it up for a new trip

Everything about the trip lives in one file: `config/trip.yaml`. The easiest way
is to give Claude Code your cities and dates and ask it to set up the new trip.
To do it yourself (the commands need the repo set up on a computer, see
"Run locally" in the README):

1. **Edit `config/trip.yaml`:**
   - `title`: the page heading, e.g. `"Italy Trip Weather"`.
   - `timezone`: the trip's time zone, e.g. `Europe/Rome`
     ([list of names](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)).
   - `home_timezone`: your home clock for "Last updated" (or delete the line).
   - `run_at`: the local time for the daily update.
   - `end_date`: last day to update (or delete it to use the last stop's end date).
   - `locations`: one entry per stop, in trip order:

     ```yaml
     - id: rome            # lowercase letters, numbers, dashes
       label: "Rome"       # shown on the page
       search: "Rome, Italy"
       accuweather_url: "…"   # see step 2
       start: 2027-05-10
       end:   2027-05-14   # travel days go under both stops
     ```

   Only put cities and dates in this file. No hotels, addresses, flight or
   booking numbers: the page and the repo can be seen by others.

2. **Find each `accuweather_url`:**

   ```sh
   python -m src.find_location "Trastevere, Rome"
   ```

   Pick the result whose name and region match, and copy its URL. Never make
   up a location number: a wrong one silently shows another city's weather.

3. **Check the config and copy the schedule line:**

   ```sh
   python -m src.plan          # lists any problems, then the dates it will capture
   python -m src.plan --cron   # prints the schedule line
   ```

   Paste the printed `- cron:` line into `.github/workflows/weather.yml` under
   `schedule:` (GitHub schedules use UTC; this converts it for you).

4. **Commit to `main`**, then run it once by hand (Actions → Weather report →
   Run workflow) and check the page.

The page address stays the same unless you rename the repository.
