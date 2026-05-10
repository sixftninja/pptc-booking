"""All Playwright interactions with the Aptus member portal.

This module is intentionally selector-heavy because the spec describes the
UI in plain English; actual selectors will likely need adjustment after the
first live test run on May 10, 2026. All selectors live in `config.SELECTORS`.

Public surface:
    launch_browser()                  -> context manager yielding (page, ctx)
    login(page, email, password)      -> raises on failure
    is_logged_in(page)                -> bool
    open_court_reservation(page)
    select_court_type(page, "hard"|"clay")
    navigate_to_date(page, target_date)
    scan_availability(page, courts)   -> {court: set(hours_available)}
    book_one_slot(page, court, hour)  -> confirmation_number (str)
    verify_reservation(page, court, hour, target_date) -> bool
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from datetime import date, datetime
from typing import Iterator

from playwright.sync_api import (
    Page,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LoginFailed(Exception):
    pass


class SlotUnavailable(Exception):
    """Raised when a slot was expected to be open but the cell is reserved."""


class CartCaptchaFailed(Exception):
    """Raised when the reCAPTCHA could not be solved on the cart page."""


class ConfirmationMissing(Exception):
    """Submission completed but no confirmation number / popup appeared."""


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def launch_browser() -> Iterator[tuple[Page, BrowserContext]]:
    """Launch Chromium NON-HEADLESS with a Mac UA. Yields (page, context)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        page = context.new_page()
        try:
            yield page, context
        finally:
            try:
                context.close()
            finally:
                browser.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def login(page: Page, email: str, password: str) -> None:
    log.info("Navigating to login page")
    page.goto(config.LOGIN_URL, wait_until="domcontentloaded")

    page.wait_for_selector(config.SELECTORS["login_email"], timeout=config.DEFAULT_TIMEOUT_MS)
    page.fill(config.SELECTORS["login_email"], email)
    page.fill(config.SELECTORS["login_password"], password)
    page.click(config.SELECTORS["login_submit"])

    # After login the URL should change; the left nav should appear.
    try:
        page.wait_for_selector(
            config.SELECTORS["nav_programs"], timeout=config.DEFAULT_TIMEOUT_MS
        )
    except PlaywrightTimeoutError as exc:
        # Surface the validation message if there is one.
        err = page.query_selector(config.SELECTORS["login_error"])
        msg = err.inner_text().strip() if err else "login did not redirect"
        raise LoginFailed(f"Login failed: {msg}") from exc

    log.info("Logged in successfully")


def is_logged_in(page: Page) -> bool:
    """Heuristic: the left nav 'Programs & Services' link is visible."""
    try:
        el = page.query_selector(config.SELECTORS["nav_programs"])
        return bool(el and el.is_visible())
    except Exception:
        return False


def session_expired(page: Page) -> bool:
    """Heuristic: the page has been bounced back to a login form."""
    try:
        if is_logged_in(page):
            return False
        # Login email + password fields visible == we got bounced.
        email_field = page.query_selector(config.SELECTORS["login_email"])
        pwd_field = page.query_selector(config.SELECTORS["login_password"])
        if email_field and pwd_field and email_field.is_visible() and pwd_field.is_visible():
            return True
        # URL-based fallback.
        url = (page.url or "").rstrip("/")
        return url.endswith("/Member") or url.endswith("/Member/Login")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def open_court_reservation(page: Page) -> None:
    """Navigate via left nav: Programs & Services → Court Reservation."""
    log.info("Opening Court Reservation page")
    # Some portals expand on hover, others on click. Click both to be safe.
    nav_root = page.query_selector(config.SELECTORS["nav_programs"])
    if nav_root:
        try:
            nav_root.click()
        except Exception:
            log.debug("Programs & Services click was a no-op; nav may already be expanded")
    page.click(config.SELECTORS["nav_court_res"])
    page.wait_for_load_state("networkidle", timeout=config.DEFAULT_TIMEOUT_MS)
    page.wait_for_selector(config.SELECTORS["type_dropdown"], timeout=config.DEFAULT_TIMEOUT_MS)


def select_court_type(page: Page, court_type: str) -> None:
    """Select 'Hard' or 'Clay' on the Type dropdown."""
    label = config.TYPE_LABEL_HARD if court_type == "hard" else config.TYPE_LABEL_CLAY
    log.info("Selecting court type: %s", label)
    dropdown = page.query_selector(config.SELECTORS["type_dropdown"])
    if dropdown is None:
        raise RuntimeError("Type dropdown not found on Court Reservation page")
    # `select_option` works for native <select>; for custom dropdowns we'd
    # need to click the label and then click the option. Try both.
    try:
        dropdown.select_option(label=label)
    except Exception:
        dropdown.click()
        page.click(f"text=\"{label}\"")
    page.wait_for_load_state("networkidle", timeout=config.SHORT_TIMEOUT_MS)
    time.sleep(0.5)


# --- Date navigation --------------------------------------------------------


def _read_calendar_date(page: Page) -> date:
    """Parse the calendar's currently-displayed date."""
    el = page.query_selector(config.SELECTORS["calendar_date_label"])
    if el is None:
        raise RuntimeError("Could not find calendar date label")
    text = el.inner_text().strip()
    # Try a few common formats: "May 17, 2026", "5/17/2026", "Sun, May 17 2026"
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%a, %B %d %Y", "%a, %b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Fall back to extracting the first date-shaped substring.
    m = re.search(r"(\w+\s+\d{1,2},?\s+\d{4})", text)
    if m:
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                continue
    raise RuntimeError(f"Could not parse calendar date label: {text!r}")


def navigate_to_date(page: Page, target: date) -> None:
    """Click the next/prev arrows until the calendar shows the target date."""
    log.info("Navigating calendar to %s", target.isoformat())
    # Bound the loop to avoid infinite clicks if something is broken.
    for _ in range(60):
        current = _read_calendar_date(page)
        if current == target:
            log.info("Calendar is on %s", target.isoformat())
            return
        if current < target:
            page.click(config.SELECTORS["calendar_next"])
        else:
            page.click(config.SELECTORS["calendar_prev"])
        # Brief pause for the calendar to redraw.
        time.sleep(0.5)
        page.wait_for_load_state("networkidle", timeout=config.SHORT_TIMEOUT_MS)
    raise RuntimeError(f"Could not navigate calendar to {target}")


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def _cell_selector(court: str, hour: int) -> str:
    """Build a selector for the calendar cell at (court, hour).

    The Aptus calendar appears to be a grid with one column per court and one
    row per hour. Without seeing the live HTML we offer a best-effort selector
    that targets common patterns: data-attribute, aria-label, or coordinate
    classes. Adjust here once we see the real markup.
    """
    hour_str = f"{hour:02d}:00"
    return (
        f'[data-court="{court}"][data-hour="{hour_str}"], '
        f'td[data-court="{court}"][data-time="{hour_str}"], '
        f'[aria-label*="Court {court}" i][aria-label*="{hour_str}"], '
        f'[aria-label*="{court.upper()}" i][aria-label*="{hour_str}"]'
    )


def _is_cell_available(cell_handle) -> bool:
    """Return True if the cell is empty/clickable (not greyed-out RESERVED)."""
    if cell_handle is None:
        return False
    try:
        text = (cell_handle.inner_text() or "").strip().upper()
        if "RESERVED" in text or "BOOKED" in text:
            return False
        cls = cell_handle.get_attribute("class") or ""
        if any(tok in cls.lower() for tok in ("reserved", "booked", "disabled", "unavailable")):
            return False
        # Aria-disabled / disabled attribute.
        for attr in ("aria-disabled", "disabled"):
            v = cell_handle.get_attribute(attr)
            if v and v.lower() in ("true", "disabled", ""):
                return False
        return True
    except Exception:
        return False


def scan_availability(page: Page, courts: list[str]) -> dict[str, set[int]]:
    """Return {court: set(open_hours)} for the courts visible on this page."""
    result: dict[str, set[int]] = {c: set() for c in courts}
    for court in courts:
        for hour in range(6, 23):  # 6am to 10pm rows per spec
            sel = _cell_selector(court, hour)
            cell = page.query_selector(sel)
            if _is_cell_available(cell):
                result[court].add(hour)
    log.info("Availability scan: %s", {c: sorted(h) for c, h in result.items()})
    return result


# ---------------------------------------------------------------------------
# Booking flow
# ---------------------------------------------------------------------------


CONFIRMATION_RE = re.compile(r"confirmation\s*(?:number|#)?\s*[:\-]?\s*([A-Z0-9\-]+)", re.I)

# Server-side rejection patterns that can appear after clicking Go.
# Treated as SlotUnavailable: the booker dismisses the popup and moves on.
RESTRICTION_PATTERNS = [
    re.compile(r"not\s+allowed\s+to\s+book", re.I),
    re.compile(r"restriction\s+failed", re.I),
]


def _detect_restriction_error(page: Page) -> str | None:
    """Look for known post-Go restriction popups. Returns matched text or None."""
    try:
        body = page.content()
    except Exception:
        return None
    for pat in RESTRICTION_PATTERNS:
        m = pat.search(body)
        if m:
            return m.group(0)
    return None


def _dismiss_restriction_popup(page: Page) -> None:
    """Click Ok on a post-Go error dialog (if one is visible)."""
    for sel in (
        config.SELECTORS["restriction_dialog_ok"],
        '.ui-dialog-buttonset button',
        'div[role="dialog"] button',
    ):
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                return
        except Exception:
            continue
    log.debug("No dismissable button found for restriction popup")


def _click_cell(page: Page, court: str, hour: int) -> None:
    sel = _cell_selector(court, hour)
    cell = page.query_selector(sel)
    if cell is None:
        raise SlotUnavailable(f"Cell not found for {court} {hour:02d}:00")
    if not _is_cell_available(cell):
        raise SlotUnavailable(f"Cell is reserved for {court} {hour:02d}:00")
    cell.click()
    page.wait_for_selector(config.SELECTORS["modal"], timeout=config.DEFAULT_TIMEOUT_MS)


def _fill_modal_and_submit(page: Page) -> None:
    log.info("Filling booking modal")
    modal = page.query_selector(config.SELECTORS["modal"])
    if modal is None:
        raise RuntimeError("Booking modal did not appear")

    # Attendee dropdown.
    attendee = modal.query_selector(config.SELECTORS["modal_attendee"])
    if attendee is not None:
        try:
            attendee.select_option(label=config.ATTENDEE_NAME)
        except Exception:
            attendee.click()
            page.click(f'text="{config.ATTENDEE_NAME}"')

    # Item Details dropdown is pre-selected by the site for each slot.
    # Do NOT touch it — the site picks the correct option for the court/time.

    # Waiver checkbox.
    waiver = modal.query_selector(config.SELECTORS["modal_waiver"])
    if waiver is None:
        # Try whole page in case selector resolves outside modal.
        waiver = page.query_selector(config.SELECTORS["modal_waiver"])
    if waiver is None:
        raise RuntimeError("Waiver checkbox not found")
    if not waiver.is_checked():
        waiver.check()

    # Go button.
    page.click(config.SELECTORS["modal_go"])
    page.wait_for_load_state("networkidle", timeout=config.DEFAULT_TIMEOUT_MS)


def _solve_cart_and_submit(page: Page) -> None:
    """Handle the cart / payment / reCAPTCHA / submit / confirmation popup."""
    # Lazy import so unit tests for other modules don't pull in capsolver.
    import captcha

    log.info("Cart page loaded — solving reCAPTCHA")
    # Scroll down so the reCAPTCHA is in view (helps non-virtual scroll bugs).
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(0.5)

    try:
        captcha.solve_recaptcha(page)
    except captcha.CaptchaError as exc:
        raise CartCaptchaFailed(str(exc)) from exc

    # Submit the cart.
    submit_btn = page.query_selector(config.SELECTORS["cart_submit"])
    if submit_btn is None:
        raise RuntimeError("Cart submit button not found")
    submit_btn.click()


def _capture_confirmation(page: Page) -> str:
    """Wait for the confirmation message + popup, dismiss popup, return number."""
    # Either a popup dialog or an inline message — handle both.
    popup_text_holder: dict[str, str] = {}

    def on_dialog(d):
        popup_text_holder["text"] = d.message
        try:
            d.accept()
        except Exception:
            pass

    page.on("dialog", on_dialog)

    try:
        page.wait_for_selector(
            config.SELECTORS["confirmation_text"], timeout=config.DEFAULT_TIMEOUT_MS
        )
    except PlaywrightTimeoutError:
        if not popup_text_holder.get("text"):
            raise ConfirmationMissing("Confirmation message did not appear")

    # Dismiss popup OK button if present (some implementations render an in-page modal).
    ok_btn = page.query_selector(config.SELECTORS["confirmation_popup_ok"])
    if ok_btn:
        try:
            ok_btn.click()
        except Exception:
            log.debug("OK button click failed; popup may already be closed")

    # Pull confirmation number from inline text or popup text.
    body_text = page.content()
    candidates = [body_text, popup_text_holder.get("text", "")]
    for src in candidates:
        m = CONFIRMATION_RE.search(src)
        if m:
            number = m.group(1)
            log.info("Captured confirmation #%s", number)
            return number
    raise ConfirmationMissing("Booking flow finished but no confirmation number found")


def book_one_slot(page: Page, court: str, hour: int) -> str:
    """Book a single 1-hour slot. Returns the confirmation number string."""
    log.info("Attempting to book Court %s at %02d:00", court.upper(), hour)
    _click_cell(page, court, hour)
    _fill_modal_and_submit(page)
    # Server may reject the slot post-Go ("Not allowed to book in this court",
    # "start time restriction failed", etc.). Dismiss and treat as unavailable
    # so the caller can try the next candidate.
    err = _detect_restriction_error(page)
    if err:
        log.warning("Slot %s@%02d:00 rejected by server: %s", court, hour, err)
        _dismiss_restriction_popup(page)
        raise SlotUnavailable(f"Server rejected slot ({err})")
    _solve_cart_and_submit(page)
    return _capture_confirmation(page)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def open_my_reservations(page: Page) -> None:
    log.info("Opening My Reservations")
    nav_root = page.query_selector(config.SELECTORS["nav_account"])
    if nav_root:
        try:
            nav_root.click()
        except Exception:
            pass
    page.click(config.SELECTORS["nav_my_reservations"])
    page.wait_for_load_state("networkidle", timeout=config.DEFAULT_TIMEOUT_MS)


def verify_reservation(page: Page, court: str, hour: int, target_date: date) -> bool:
    """Look on the My Reservations page for evidence of the given booking."""
    body = page.content().lower()
    date_strs = [
        target_date.strftime("%-m/%-d/%Y").lower(),
        target_date.strftime("%-m/%-d/%y").lower(),
        target_date.strftime("%b %-d, %Y").lower(),
        target_date.strftime("%B %-d, %Y").lower(),
        target_date.strftime("%Y-%m-%d"),
    ]
    hour_strs = [f"{hour:02d}:00", f"{hour}:00", f"{hour % 12 or 12}:00"]

    has_date = any(s in body for s in date_strs)
    has_hour = any(s in body for s in hour_strs)
    has_court = court.lower() in body or court.upper() in page.content()

    found = has_date and has_hour and has_court
    log.info("verify_reservation court=%s hour=%d date=%s -> %s "
             "(date_match=%s hour_match=%s court_match=%s)",
             court, hour, target_date, found, has_date, has_hour, has_court)
    return found
