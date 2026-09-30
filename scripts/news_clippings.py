"""News clippings for a narrative: the top of each article - masthead, headline, date - as images.

Kendall, 30 Sep 2026 (Etihad Rail): "i want news clipping dropped in". Research only, internal. Only the headline area
is kept (masthead down to just below the headline), never the article text. Cookie banners: the non-essential
option is declined where one is offered.

    python scripts/news_clippings.py <out_dir> <name=url> [<name=url> ...]
"""
import os
import sys
from playwright.sync_api import sync_playwright

HIDE_JS = """() => {
  for (const e of document.querySelectorAll('iframe, ins, [id*="google_ads"], [class*="ad-"], [class*="-ad"], [class*="advert"], [id*="ad-"], [class*="sponsor"]')) e.style.setProperty('display', 'none', 'important');
  for (const e of document.querySelectorAll('body *')) { const st = getComputedStyle(e), r = e.getBoundingClientRect();
    if (st.position === 'fixed' && r.height > 0.8 * innerHeight && r.width > 0.8 * innerWidth) { e.style.setProperty('display', 'none', 'important'); continue; }   // full-screen dimmers and sign-up walls
    if (st.position === 'fixed' && e.getBoundingClientRect().height < 400 && e.getBoundingClientRect().top > 150) e.style.setProperty('display', 'none', 'important'); }
  document.documentElement.style.overflow = 'auto'; document.body.style.overflow = 'auto';
  document.body.style.filter = 'none'; document.documentElement.style.filter = 'none';
}"""
DECLINE = ["Reject all", "Reject All", "Decline", "Only necessary", "Necessary only", "Reject", "Continue without accepting"]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    jobs = [a.split("=", 1) for a in sys.argv[2:]]
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1200, "height": 900}, device_scale_factor=2,
                             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
        for name, url in jobs:
            pg = ctx.new_page()
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=60_000)
                pg.wait_for_timeout(4000)
                for label in DECLINE:
                    b = pg.get_by_role("button", name=label, exact=True)
                    if b.count():
                        try:
                            b.first.click(timeout=2000)
                            pg.wait_for_timeout(800)
                            break
                        except Exception:
                            pass
                pg.wait_for_timeout(4000)                  # slow pages render the headline late
                h1 = pg.locator("h1:visible").first
                box = None
                try:
                    box = h1.bounding_box(timeout=8000)
                except Exception:
                    pass                                   # no findable headline: keep the top of the page
                pg.evaluate(HIDE_JS)                       # adverts and floating players off the headline
                pg.evaluate("() => window.scrollTo(0, 0)")
                pg.wait_for_timeout(1500)
                top = 0
                bottom = min(900, (box["y"] + box["height"] + 90) if box else 600)
                # the article's own column only: sidebars carry unrelated headlines that must not sit beside Naj
                width = min(1200, int(box["x"] + box["width"] + 40)) if box else 1200
                pg.screenshot(path=os.path.join(out, name + ".png"),
                              clip={"x": 0, "y": top, "width": width, "height": max(300, bottom - top)})
                print("ok  ", name, "headline:", (h1.inner_text() or "")[:90].replace("\n", " "))
            except Exception as e:
                print("FAIL", name, str(e).splitlines()[0][:100])
            finally:
                pg.close()
        br.close()


if __name__ == "__main__":
    main()
