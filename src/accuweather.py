"""AccuWeather URL building and DOM selectors.

Every selector and page-structure assumption lives in this file, so when
AccuWeather changes its layout only this file (and the fixtures in
tests/fixtures/) should need updating.

Observed structure (Oct 2026):
- Daily: /daily-weather-forecast/<key> redirects to /10-day-weather-forecast/<key>.
  One `.daily-wrapper` card per day; `.info .date` holds e.g. "Sat 10/17".
- Hourly: /hourly-weather-forecast/<key>?day=N, N=1 is today. One
  `.accordion-item.hour` row per hour; its `id` is the hour's Unix timestamp.
  A `day` beyond coverage redirects to the 10-day page (no hour rows).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

BASE = "https://www.accuweather.com"

DAILY_CARD = ".daily-wrapper"
DAILY_CARD_DATE = ".info .date"
HOUR_ROW = ".accordion-item.hour"

# Requests to these hosts are aborted: ads/trackers/consent tooling that only
# add overlays and slow the page down. Page content and styles are not here.
BLOCKED_HOST_PATTERNS = [
    "doubleclick.net", "googlesyndication.com", "googletagservices.com",
    "googletagmanager.com", "google-analytics.com", "amazon-adsystem.com",
    "adnxs.com", "rubiconproject.com", "pubmatic.com", "openx.net",
    "criteo.com", "taboola.com", "outbrain.com", "rapidedge.io", "p-n.io",
    "ketchcdn.com", "scorecardresearch.com", "chartbeat.com", "permutive",
    "moatads.com", "adsafeprotected.com", "id5-sync.com",
]

# Injected before capturing: hide ad slots and anything that floats over content.
HIDE_CSS = """
.glacier-ad, .ad, [class*="ad-container"], [id^="google_ads"], [id*="-ad-"],
.non-ad + .ad, .banner-ad, .top-ad, .adhesion-header, .sticky-ad,
#lanyard_root, .privacy-policy-banner, .policy-accept, .fc-consent-root,
.featured-video, .ps-video, .tooltip, .label-tooltip-overlay {
    display: none !important;
}
"""

# Buttons that dismiss cookie/consent/notification prompts, matched by text.
DISMISS_BUTTON_TEXT = re.compile(r"^(accept|accept all|i accept|i understand|got it|agree|ok|close|no thanks|not now)$", re.I)

ACCESS_DENIED_MARKERS = ("Access Denied", "Pardon Our Interruption", "Request unsuccessful")

_KEY_URL = re.compile(r"^(https://www\.accuweather\.com/[a-z]{2}/[a-z]{2}/[^/]+)/([^/]+)/weather-forecast/\2/?$")
_MD = re.compile(r"(\d{1,2})/(\d{1,2})")


@dataclass(frozen=True)
class LocationUrls:
    base: str  # e.g. https://www.accuweather.com/en/jp/ueno
    key: str  # e.g. 2409626

    @property
    def daily(self) -> str:
        return f"{self.base}/{self.key}/daily-weather-forecast/{self.key}"

    def hourly(self, day: int) -> str:
        url = f"{self.base}/{self.key}/hourly-weather-forecast/{self.key}"
        return url if day <= 1 else f"{url}?day={day}"


def parse_location_url(url: str) -> LocationUrls:
    """Split a city page URL (the `accuweather_url` in trip.yaml) into base + key."""
    m = _KEY_URL.match(url.split("?")[0])
    if not m:
        raise ValueError(f"Not an AccuWeather city forecast URL: {url!r}")
    return LocationUrls(base=m.group(1), key=m.group(2))


def parse_card_date(text: str, reference: date) -> date | None:
    """'Sat\\n10/17' -> date, picking the year closest to `reference`."""
    m = _MD.search(text or "")
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    candidates = []
    for y in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(date(y, month, day))
        except ValueError:
            pass
    return min(candidates, key=lambda d: abs((d - reference).days)) if candidates else None


def parse_hour_id(row_id: str | None, tz: ZoneInfo) -> datetime | None:
    """Hour rows carry their Unix timestamp as the element id."""
    if not row_id or not row_id.isdigit():
        return None
    return datetime.fromtimestamp(int(row_id), tz)


def is_blocked(title: str, status: int | None) -> bool:
    return (status is not None and status in (401, 403, 429)) or any(m in (title or "") for m in ACCESS_DENIED_MARKERS)


def is_hourly_url(url: str) -> bool:
    return "/hourly-weather-forecast/" in url


# --- helpers operating on a live Playwright page (also used by fixture tests) ---

def daily_cards(page, reference: date) -> list[tuple[date, object]]:
    """[(date, element_handle)] for every day card on the daily page."""
    out = []
    for el in page.query_selector_all(DAILY_CARD):
        label = el.query_selector(DAILY_CARD_DATE)
        d = parse_card_date(label.inner_text() if label else "", reference)
        if d:
            out.append((d, el))
    return out


def hour_rows(page, tz: ZoneInfo) -> list[tuple[datetime, object]]:
    """[(hour_start, element_handle)] for every hour row on an hourly page."""
    out = []
    for el in page.query_selector_all(HOUR_ROW):
        t = parse_hour_id(el.get_attribute("id"), tz)
        if t:
            out.append((t, el))
    return out
