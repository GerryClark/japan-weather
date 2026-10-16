"""Debug helper: load one AccuWeather page the way capture.py does and report
what the browser sees (element boxes, visibility, overlay candidates).

Usage:
    python -m src.diagnose <url> [--b64]

--b64 prints a small JPEG of the viewport and of the crop as base64 so it can
be inspected from a CI log when artifacts can't be downloaded.
"""
from __future__ import annotations

import argparse
import base64
import io
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

from src import accuweather as aw
from src.capture import crop_png, new_context, open_page


def thumb_b64(png: bytes, width: int = 480) -> str:
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=45)
    return base64.b64encode(buf.getvalue()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--b64", action="store_true")
    ap.add_argument("--no-block", action="store_true", help="don't block ad/consent hosts")
    args = ap.parse_args()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chromium")
        except Exception:
            browser = pw.chromium.launch()
        page = new_context(browser, block_hosts=not args.no_block).new_page()
        print('host blocking:', 'off' if args.no_block else 'on')
        open_page(page, args.url)
        print("url:", page.url, "| title:", page.title())
        sel = aw.HOUR_ROW if aw.is_hourly_url(page.url) else aw.DAILY_CARD
        els = page.query_selector_all(sel)
        print(f"{sel}: {len(els)} elements")
        for el in els[:3]:
            print("  ", el.evaluate("""e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                return {x: r.x, y: r.y + scrollY, w: r.width, h: r.height, opacity: s.opacity,
                        visibility: s.visibility, display: s.display, text: e.innerText.slice(0, 40)}; }"""))
        print("body:", page.evaluate("""() => ({cls: document.body.className, h: document.body.scrollHeight,
            opacity: getComputedStyle(document.body).opacity})"""))
        if args.b64:
            print("VIEWPORT_B64", thumb_b64(page.screenshot(type="png")))
            if els:
                try:
                    print("CROP_B64", thumb_b64(crop_png(page, els[:5])))
                except Exception as e:
                    print("crop failed:", e)
                    print("VIEWPORT_AFTER_B64", thumb_b64(page.screenshot(type="png")))
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
