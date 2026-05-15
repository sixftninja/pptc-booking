"""Walk the real PPTC member portal end-to-end and dump every page's
structure to fixtures/ so the booker can be rebuilt against real DOM.

Captures, for each page:
  - <name>.html        full rendered HTML (after JS, after waits)
  - <name>.summary.json structured JSON of the elements that matter
  - <name>.png         viewport screenshot

Pages walked:
  01_login              before sign-in
  02_dashboard          after sign-in (left nav, JS handlers)
  03_calendar_today     Court Reservation, Hard tab, today
  04_calendar_target    Court Reservation, Hard tab, today+7
  05_calendar_clay      Court Reservation, Clay tab, today+7
  06_modal              Booking modal opened on a real available slot
  07_cart               Cart page (DOES NOT SUBMIT — explicit Clear Cart on exit)
  08_my_reservations    Account Activity → My Reservations

Run:
    /Users/anand/miniconda3/envs/pptc-bot/bin/python tools/inspect_site.py

Reads credentials from /Users/anand/Desktop/pptc-booking/.env.
Never submits the cart. Clears any pending cart item on exit.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Page

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
SHOTS = FIXTURES / "screenshots"
load_dotenv(ROOT / ".env")

EMAIL = os.getenv("PPTC_EMAIL")
PASSWORD = os.getenv("PPTC_PASSWORD")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

LOGIN_URL = "https://prospectpark.aptussoft.com/Member"
CALENDAR_URL = "https://prospectpark.aptussoft.com/Member/Aptus/Calender"
DASHBOARD_URL = "https://prospectpark.aptussoft.com/Member/Aptus/Main"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def save(page: Page, label: str, summary: dict) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{label}.html").write_text(page.content())
    (FIXTURES / f"{label}.summary.json").write_text(json.dumps(summary, indent=2, default=str))
    try:
        page.screenshot(path=str(SHOTS / f"{label}.png"), full_page=True)
    except Exception as exc:
        print(f"  screenshot failed: {exc}")
    print(f"  saved {label}.{{html,summary.json,png}}")


def summarize_login_form(page: Page) -> dict:
    return page.evaluate("""
    () => ({
        url: location.href,
        title: document.title,
        inputs: Array.from(document.querySelectorAll('input')).map(i => ({
            type: i.type, name: i.name, id: i.id,
            placeholder: i.placeholder, classes: i.className,
            visible: i.offsetParent !== null,
        })),
        forms: Array.from(document.querySelectorAll('form')).map(f => ({
            id: f.id, action: f.action, method: f.method,
        })),
        buttons: Array.from(document.querySelectorAll('button, input[type="submit"]'))
            .map(b => ({tag: b.tagName, type: b.type, id: b.id, name: b.name,
                        text: (b.innerText||b.value||'').trim().slice(0,80),
                        classes: b.className})),
        recaptcha_div: !!document.querySelector('.g-recaptcha'),
        recaptcha_iframe: !!document.querySelector('iframe[src*="recaptcha"]'),
    })
    """)


def summarize_dashboard(page: Page) -> dict:
    return page.evaluate("""
    () => ({
        url: location.href,
        title: document.title,
        nav_links: Array.from(document.querySelectorAll('a, .nav-link'))
            .filter(a => (a.innerText||'').trim().length)
            .slice(0, 60)
            .map(a => ({
                text: (a.innerText||'').trim().slice(0,60),
                href: a.getAttribute('href') || '',
                onclick: a.getAttribute('onclick') || '',
                id: a.id, classes: a.className,
            })),
        iframes: Array.from(document.querySelectorAll('iframe')).map(f => ({
            id: f.id, src: f.src, name: f.name,
        })),
    })
    """)


def summarize_calendar(page: Page) -> dict:
    """Grab everything needed to understand the FullCalendar layout:
    - Resource select + currently selected option
    - Header h2 (date label)
    - Each court column: id, display label, top, height, content div id
    - Each fc-event: bounding box, court column it sits in, title
    - Each fc-agenda-slots row: time label, top offset, height
    """
    return page.evaluate("""
    () => {
        const out = {
            url: location.href,
            title: document.title,
        };
        const r = document.querySelector('#Resource');
        out.resource_select = r ? {
            id: r.id, name: r.name,
            options: Array.from(r.options).map(o => o.text.trim()),
            selected: r.options[r.selectedIndex] ? r.options[r.selectedIndex].text.trim() : null,
        } : null;

        const h2 = document.querySelector('.fc-header-title h2, .fc-header-title');
        out.date_label = h2 ? (h2.innerText || '').trim() : null;

        const headerLeft = document.querySelector('.fc-header-left');
        out.nav_buttons = headerLeft ? Array.from(headerLeft.querySelectorAll('span.fc-button')).map(b => ({
            text: (b.innerText||'').trim().slice(0,30),
            classes: b.className,
        })) : [];

        // Court columns — header row.
        out.columns = Array.from(document.querySelectorAll('.fc-agenda-days thead th'))
            .filter(th => th.className.includes('fc-resourceid-'))
            .map(th => {
                const cls = th.className || '';
                const match = cls.match(/fc-resourceid-([A-Za-z0-9]+)/);
                const courtId = match ? match[1] : null;
                const r = th.getBoundingClientRect();
                return {
                    id_attr: th.id,
                    courtId: courtId,
                    label: (th.innerText||'').trim(),
                    classes: cls,
                    rect: {top: r.top, left: r.left, width: r.width, height: r.height},
                };
            });

        // Body row — same columns but as <td>, these are the click targets.
        out.body_columns = Array.from(document.querySelectorAll('.fc-agenda-days tbody td'))
            .filter(td => td.className.includes('fc-resourceid-'))
            .map(td => {
                const cls = td.className;
                const match = cls.match(/fc-resourceid-([A-Za-z0-9]+)/);
                const courtId = match ? match[1] : null;
                const r = td.getBoundingClientRect();
                return {
                    id_attr: td.id,
                    courtId: courtId,
                    classes: cls,
                    rect: {top: r.top, left: r.left, width: r.width, height: r.height},
                    inner_div_id: (td.querySelector('[id^="div-ic"]') || {}).id || '',
                };
            });

        // The slot label table — gives us pixel-per-hour math.
        out.slot_rows = Array.from(document.querySelectorAll('.fc-agenda-slots tbody tr'))
            .map((tr, i) => {
                const th = tr.querySelector('th');
                const r = tr.getBoundingClientRect();
                return {
                    index: i,
                    classes: tr.className,
                    label: (th ? th.innerText : '').trim(),
                    rect: {top: r.top, height: r.height},
                };
            });

        // All RESERVED overlays — absolute-positioned events in each column.
        out.events = Array.from(document.querySelectorAll('.fc-event')).map(e => {
            const r = e.getBoundingClientRect();
            const titleEl = e.querySelector('.fc-event-title');
            const timeEl = e.querySelector('.fc-event-time');
            return {
                title: titleEl ? (titleEl.innerText || '').trim() : '',
                time: timeEl ? (timeEl.innerText || '').trim() : '',
                classes: e.className,
                style_top: e.style.top,
                style_left: e.style.left,
                style_height: e.style.height,
                style_width: e.style.width,
                rect: {top: r.top, left: r.left, width: r.width, height: r.height},
            };
        });

        return out;
    }
    """)


def summarize_modal(page: Page) -> dict:
    return page.evaluate("""
    () => {
        const modals = Array.from(document.querySelectorAll('[role="dialog"], .modal, .ui-dialog'))
            .filter(m => m.offsetParent !== null);
        if (modals.length === 0) return {visible_modals: 0};
        // Pick the most recently visible-looking one
        const m = modals[modals.length - 1];
        return {
            visible_modals: modals.length,
            outer_id: m.id,
            outer_classes: m.className,
            inputs: Array.from(m.querySelectorAll('input, select, textarea')).map(el => ({
                tag: el.tagName, type: el.type, id: el.id, name: el.name,
                value: el.value,
                checked: el.type === 'checkbox' ? el.checked : null,
                readonly: el.hasAttribute('readonly'),
                options: el.tagName === 'SELECT'
                    ? Array.from(el.options).map(o => ({text: o.text.trim(), selected: o.selected}))
                    : null,
                visible: el.offsetParent !== null,
            })),
            buttons: Array.from(m.querySelectorAll('button, input[type="submit"], input[type="button"]'))
                .map(b => ({tag: b.tagName, type: b.type, id: b.id, name: b.name,
                            text: (b.innerText||b.value||'').trim().slice(0,60),
                            classes: b.className})),
            html_snippet: m.outerHTML.slice(0, 4000),
        };
    }
    """)


def summarize_cart(page: Page) -> dict:
    return page.evaluate("""
    () => ({
        url: location.href,
        title: document.title,
        h_tags: Array.from(document.querySelectorAll('h1,h2,h3,h4'))
            .map(h => ({tag: h.tagName, text: (h.innerText||'').trim().slice(0,80), id: h.id, classes: h.className})),
        recaptcha_div: Array.from(document.querySelectorAll('.g-recaptcha')).map(d => ({
            sitekey: d.getAttribute('data-sitekey') || '',
            classes: d.className,
            id: d.id,
        })),
        recaptcha_iframes: Array.from(document.querySelectorAll('iframe[src*="recaptcha"]')).map(f => ({
            src: f.src, title: f.title,
        })),
        forms: Array.from(document.querySelectorAll('form')).map(f => ({
            id: f.id, action: f.action, method: f.method,
        })),
        buttons: Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'))
            .map(b => ({tag: b.tagName, type: b.type, id: b.id, name: b.name,
                        text: (b.innerText||b.value||'').trim().slice(0,80),
                        classes: b.className,
                        onclick: b.getAttribute('onclick') || ''})),
        text_blocks: Array.from(document.querySelectorAll('div, p, span'))
            .map(e => (e.innerText||'').trim())
            .filter(t => /\\$|cart|amount|price|total|payment|reserved|booked|location|member/i.test(t))
            .slice(0, 30),
    })
    """)


def summarize_my_reservations(page: Page) -> dict:
    return page.evaluate("""
    () => ({
        url: location.href,
        title: document.title,
        h_tags: Array.from(document.querySelectorAll('h1,h2,h3,h4'))
            .map(h => ({tag: h.tagName, text: (h.innerText||'').trim().slice(0,80)})),
        tables: Array.from(document.querySelectorAll('table')).slice(0,3).map(t => ({
            id: t.id, classes: t.className, rows: t.rows.length,
            sample: t.rows.length > 1 ? t.rows[1].outerHTML.slice(0, 800) : '',
        })),
        reservation_items: Array.from(document.querySelectorAll('[class*="reservation" i], .res-item, tr'))
            .filter(el => /reserv|court|attend|member|booking/i.test(el.className) || /Court \\d+[ab]/.test(el.innerText||''))
            .slice(0, 10)
            .map(el => ({
                tag: el.tagName, classes: el.className,
                text: (el.innerText||'').trim().slice(0,400),
            })),
    })
    """)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _wait_calendar_ready(page: Page, timeout_ms: int = 90000) -> None:
    """Wait until Knockout has populated the Resource dropdown AND at least
    one fc-resourceid-* column header has rendered.

    The site has an intermittent JS init bug (404 on jquery-3.3.1.min.js)
    that sometimes breaks the calendar's AJAX chain. We retry by reloading
    the page once if the first wait fails."""
    try:
        page.wait_for_function(
            """() => {
                const r = document.querySelector('#Resource');
                const cols = document.querySelectorAll('th[class*="fc-resourceid-"]');
                return r && r.options.length > 0 && cols.length > 0;
            }""",
            timeout=timeout_ms,
        )
    except PWTimeout:
        print("  calendar didn't populate — reloading once")
        page.reload(wait_until="networkidle", timeout=60000)
        page.wait_for_function(
            """() => {
                const r = document.querySelector('#Resource');
                const cols = document.querySelectorAll('th[class*="fc-resourceid-"]');
                return r && r.options.length > 0 && cols.length > 0;
            }""",
            timeout=timeout_ms,
        )
    page.wait_for_timeout(1500)  # let absolute-positioned events finish settling


def click_court_reservation_via_nav(page: Page) -> None:
    """Navigate directly to the calendar URL post-login."""
    page.goto(CALENDAR_URL, wait_until="networkidle", timeout=60000)
    _wait_calendar_ready(page)


def switch_resource(page: Page, label: str) -> None:
    """Switch the Resource dropdown to 'Hard' or 'Clay' and wait for redraw."""
    page.select_option("#Resource", label=label)
    # Wait for column headers to reflect the new resource (count changes
    # between Hard=2 and Clay=6, or labels change).
    page.wait_for_timeout(2500)
    _wait_calendar_ready(page)


def navigate_forward_days(page: Page, days: int) -> None:
    """Click the FullCalendar next-day arrow in the header N times."""
    btn_sel = ".fc-header-left .fc-button-next"
    for _ in range(days):
        page.click(btn_sel)
        page.wait_for_timeout(800)


def find_first_available_hour(summary: dict) -> tuple[str, int] | None:
    """Given a calendar summary, find any (courtId, hour) that's not covered
    by an fc-event. Returns None if nothing is open. Crude — uses pixel
    overlap between event rect and slot row rect."""
    rows = summary.get("slot_rows") or []
    cols = summary.get("body_columns") or []
    events = summary.get("events") or []
    # Map slot_rows: integer hour → (top, bottom)
    hour_ranges = {}
    for row in rows:
        label = row.get("label", "").lower().strip()
        if not label or label in ("", "&nbsp;"):
            continue
        # "9am", "10am", "12pm", "1pm" → 24h hour
        try:
            num = int("".join(ch for ch in label if ch.isdigit()))
            ampm = "pm" if "pm" in label else "am"
            hr = num if ampm == "am" or num == 12 else num + 12
            if ampm == "am" and num == 12:
                hr = 0
            top = row["rect"]["top"]
            bottom = top + row["rect"]["height"]
            hour_ranges[hr] = (top, bottom)
        except (ValueError, KeyError):
            continue

    for col in cols:
        col_left = col["rect"]["left"]
        col_right = col_left + col["rect"]["width"]
        col_id = col.get("courtId")
        # Determine which hours are covered by events in this column
        covered = set()
        for ev in events:
            ex = ev["rect"]["left"]
            ew = ev["rect"]["width"]
            # Event belongs to this column if its center sits inside column bounds
            if not (col_left <= ex + ew / 2 <= col_right):
                continue
            ey = ev["rect"]["top"]
            eb = ey + ev["rect"]["height"]
            for hr, (rtop, rbot) in hour_ranges.items():
                # overlap?
                if eb > rtop and ey < rbot:
                    covered.add(hr)
        for hr in sorted(hour_ranges):
            if hr in covered:
                continue
            if hr < 7 or hr > 21:
                continue
            return (col_id, hr)
    return None


def click_slot(page: Page, courtId: str, hour: int, slot_top: float, slot_bottom: float,
               col_left: float, col_width: float) -> None:
    """Click in the middle of (column × hour) coordinates. Coordinates are
    in viewport space."""
    x = col_left + col_width / 2
    y = (slot_top + slot_bottom) / 2
    print(f"  clicking column={courtId} hour={hour} at viewport ({x:.0f}, {y:.0f})")
    page.mouse.click(x, y)
    page.wait_for_timeout(2500)


def main() -> int:
    if not (EMAIL and PASSWORD):
        print("FAIL: PPTC_EMAIL / PPTC_PASSWORD missing", file=sys.stderr)
        return 1

    target_date = date.today() + timedelta(days=7)
    print(f"Inspector starting. Today={date.today()}, target={target_date}")
    print(f"Output: {FIXTURES}")

    cart_reached = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=UA, viewport={"width": 1440, "height": 900},
            locale="en-US", timezone_id="America/New_York",
            service_workers="block",  # ServiceWorker registration is failing on Aptus and may be making things flakier
        )
        ctx.clear_cookies()
        ctx.set_default_timeout(45000)
        page = ctx.new_page()

        try:
            # 01 — login page (pre-auth)
            print("\n01_login: capturing pre-auth page")
            page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
            save(page, "01_login", summarize_login_form(page))

            # Sign in
            page.fill("#email", EMAIL)
            page.fill("#password", PASSWORD)
            page.click("#btnSignIn")
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2500)

            # 02 — dashboard
            print("\n02_dashboard: capturing post-auth dashboard")
            save(page, "02_dashboard", summarize_dashboard(page))

            # 03 — calendar today, Hard tab
            print("\n03_calendar_hard_today: capturing Hard tab today")
            click_court_reservation_via_nav(page)
            switch_resource(page, "Hard")
            save(page, "03_calendar_hard_today", summarize_calendar(page))

            # 04 — calendar target, Hard tab
            print(f"\n04_calendar_hard_target: navigating forward 7 days to {target_date}")
            navigate_forward_days(page, 7)
            target_summary_hard = summarize_calendar(page)
            save(page, "04_calendar_hard_target", target_summary_hard)

            # 05 — calendar target, Clay tab (from same forward-7 position)
            print("\n05_calendar_clay_target: switching to Clay tab")
            switch_resource(page, "Clay")
            target_summary_clay = summarize_calendar(page)
            save(page, "05_calendar_clay_target", target_summary_clay)

            # 06/07 — pick an available slot, open modal, capture, then go to cart
            slot = (find_first_available_hour(target_summary_clay)
                    or find_first_available_hour(target_summary_hard))
            if slot is None:
                # Try today, in case target is fully booked
                print("\n  no openings on target date — falling back to today (Hard)")
                navigate_forward_days(page, -7) if False else None
                # We can't go backwards easily without prev; just re-load Calender
                page.goto(CALENDAR_URL, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                switch_resource(page, "Hard")
                today_summary = summarize_calendar(page)
                slot = find_first_available_hour(today_summary)

            if slot is None:
                print("  WARN: could not find any open slot — skipping modal/cart capture")
            else:
                courtId, hour = slot
                # We need fresh viewport coords from current page state
                latest = summarize_calendar(page)
                col_match = next((c for c in latest["body_columns"] if c["courtId"] == courtId), None)
                row_match = None
                for row in latest["slot_rows"]:
                    label = row.get("label", "").lower().strip()
                    if not label:
                        continue
                    try:
                        num = int("".join(ch for ch in label if ch.isdigit()))
                        ampm = "pm" if "pm" in label else "am"
                        h = num if ampm == "am" or num == 12 else num + 12
                        if ampm == "am" and num == 12:
                            h = 0
                        if h == hour:
                            row_match = row
                            break
                    except ValueError:
                        continue

                if col_match and row_match:
                    print(f"\n06_modal: opening modal on {courtId} at hour {hour}")
                    click_slot(page, courtId, hour,
                               row_match["rect"]["top"],
                               row_match["rect"]["top"] + row_match["rect"]["height"],
                               col_match["rect"]["left"], col_match["rect"]["width"])
                    page.wait_for_timeout(1500)
                    save(page, "06_modal", summarize_modal(page))

                    # 07 — click Go to reach cart
                    print("\n07_cart: clicking Go to reach cart page")
                    # Find Go button in the modal
                    go_btn = page.query_selector("button:has-text('Go'), input[type='submit'][value='Go']")
                    if go_btn is None:
                        # Maybe inside an iframe? Try frames
                        for frame in page.frames:
                            try:
                                go_btn = frame.query_selector("button:has-text('Go')")
                                if go_btn:
                                    break
                            except Exception:
                                pass
                    if go_btn:
                        go_btn.click()
                        page.wait_for_load_state("networkidle", timeout=60000)
                        page.wait_for_timeout(3500)
                        cart_reached = True
                        save(page, "07_cart", summarize_cart(page))
                    else:
                        print("  Could not find Go button — modal capture saved, cart skipped")

            # 08 — My Reservations
            print("\n08_my_reservations: navigating to My Reservations")
            try:
                # The dashboard's My Reservations link uses JS. Easiest: navigate
                # via known URL pattern. Aptus often uses /Member/Aptus/<file>.
                page.goto("https://prospectpark.aptussoft.com/Member/Aptus/SByName?fn=frmMemberAppt",
                          wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2500)
                save(page, "08_my_reservations", summarize_my_reservations(page))
            except Exception as exc:
                print(f"  My Reservations capture failed: {exc}")

        except Exception as exc:
            print(f"\n!!! Inspector hit an error: {exc}")
            traceback.print_exc()
            try:
                save(page, "99_error_state", {"error": str(exc), "trace": traceback.format_exc()})
            except Exception:
                pass

        finally:
            # Cleanup: if we reached the cart, clear it before logging out so
            # there's no pending booking left in the user's session.
            if cart_reached:
                print("\nCleanup: clicking Clear Cart")
                try:
                    cc = page.query_selector("button:has-text('Clear Cart')")
                    if cc:
                        cc.click()
                        page.wait_for_timeout(2000)
                        # Some sites confirm — accept any confirm dialog
                        try:
                            page.on("dialog", lambda d: d.accept())
                        except Exception:
                            pass
                        print("  Clear Cart clicked")
                    else:
                        print("  Clear Cart button not found — please verify cart is empty manually")
                except Exception as exc:
                    print(f"  Clear Cart failed: {exc} — please verify cart is empty manually")

            page.wait_for_timeout(1500)
            ctx.close()
            browser.close()

    print(f"\nDone. Files in {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
