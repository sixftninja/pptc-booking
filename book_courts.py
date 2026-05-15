"""Main entry point for the PPTC court booking system.

Run via cron at 5:55am Sat/Sun. Logs everything, scans availability, walks
the 44-step priority list, books the first satisfiable entry, sends an
appropriate email, and updates the GitHub Pages dashboard.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

import browser
import config
import dashboard
import notifier
import test_capture

log = logging.getLogger("pptc")

REPO_DIR = Path(__file__).resolve().parent
LOGS_DIR = REPO_DIR / "logs"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"courts_{date.today().isoformat()}.log"
    fmt = "%(asctime)s %(levelname)s %(name)s | %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_path)]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


# ---------------------------------------------------------------------------
# Date guards
# ---------------------------------------------------------------------------


def today() -> date:
    return date.today()


def in_active_window(d: date) -> bool:
    return config.ACTIVE_START_DATE <= d <= config.ACTIVE_END_DATE


def target_date_for(d: date) -> date:
    return d + timedelta(days=7)


# ---------------------------------------------------------------------------
# Candidate generation per priority entry
# ---------------------------------------------------------------------------


def _permit_court_allowed(court: str, hour: int) -> bool:
    """Permit courts (4b, 5b) cannot be booked for slots starting at 19:00 or later."""
    if court in config.PERMIT_COURTS and hour > config.PERMIT_COURT_LATEST_START_HOUR:
        return False
    return True


def _candidates_two_hour_same(availability: dict[str, set[int]],
                              courts: list[str], start: int) -> list[tuple[str, str]]:
    """All courts that have both `start` and `start+1` open. Order matters."""
    out = []
    for c in courts:
        # Both halves of a 2-hour block must be allowed for this court.
        if not (_permit_court_allowed(c, start) and _permit_court_allowed(c, start + 1)):
            continue
        hrs = availability.get(c, set())
        if start in hrs and (start + 1) in hrs:
            out.append((c, c))
    return out


def _candidates_two_hour_different(availability: dict[str, set[int]],
                                   courts: list[str], start: int) -> list[tuple[str, str]]:
    """All ordered (a, b) pairs where a != b, a has hour 1, b has hour 2."""
    have_first = [c for c in courts
                  if _permit_court_allowed(c, start)
                  and start in availability.get(c, set())]
    have_second = [c for c in courts
                   if _permit_court_allowed(c, start + 1)
                   and (start + 1) in availability.get(c, set())]
    out = []
    for a in have_first:
        for b in have_second:
            if a != b:
                out.append((a, b))
    return out


def _candidates_one_hour(availability: dict[str, set[int]],
                         courts: list[str], hour: int) -> list[str]:
    return [c for c in courts
            if _permit_court_allowed(c, hour)
            and hour in availability.get(c, set())]


# ---------------------------------------------------------------------------
# Session recovery wrapper
# ---------------------------------------------------------------------------


class SessionContext:
    """Holds login credentials so any helper can re-authenticate on demand."""

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.relogin_count = 0

    def ensure(self, page) -> None:
        """If the session has expired, log back in once. Raises on repeat failure."""
        if not browser.session_expired(page):
            return
        if self.relogin_count >= 3:
            raise browser.LoginFailed("Session expired repeatedly; aborting")
        log.warning("Session appears expired — re-authenticating (attempt %d)", self.relogin_count + 1)
        self.relogin_count += 1
        browser.login(page, self.email, self.password)


# ---------------------------------------------------------------------------
# Priority loop
# ---------------------------------------------------------------------------


def _scan_all(page, target: date, sess: SessionContext) -> dict[str, set[int]]:
    """Open Court Reservation and scan both Hard and Clay availability."""
    sess.ensure(page)
    browser.open_court_reservation(page)
    browser.select_court_type(page, "hard")
    browser.navigate_to_date(page, target)
    hard = browser.scan_availability(page, config.HARD_COURTS)

    browser.select_court_type(page, "clay")
    try:
        browser.navigate_to_date(page, target)
    except Exception:
        log.warning("Calendar may have reset on type switch — reattempting")
    clay = browser.scan_availability(page, config.CLAY_COURTS)

    merged: dict[str, set[int]] = {}
    merged.update(hard)
    merged.update(clay)
    return merged


def _mark_unavailable(availability: dict[str, set[int]], court: str, hour: int) -> None:
    """Drop (court, hour) from the in-memory availability map so future
    priority entries don't try the same slot again."""
    bucket = availability.get(court)
    if bucket is not None:
        bucket.discard(hour)


def _try_two_hour_pair(page, target: date, court_type: str,
                       court_a: str, hour_a: int,
                       court_b: str, hour_b: int,
                       sess: SessionContext,
                       availability: dict[str, set[int]]) -> dict | None:
    """Attempt to book hour 1 then hour 2.

    Return values:
      None                          -> hour 1 failed (slot taken / restricted). Caller can try next pair.
      {status: 'captcha_no_booking'}-> CAPTCHA failed before any hour booked. Caller aborts.
      {status: 'ok_full', ...}      -> both hours booked.
      {status: 'ok_partial', ...}   -> hour 1 booked, hour 2 lost (slot taken or CAPTCHA).
                                       Caller must NOT continue.
    """
    sess.ensure(page)
    try:
        conf_a = browser.book_one_slot(page, court_a, hour_a)
    except browser.SlotUnavailable:
        _mark_unavailable(availability, court_a, hour_a)
        return None
    except browser.CartCaptchaFailed:
        notifier.send_captcha_alert(target, court_a, hour_a)
        return {"status": "captcha_no_booking"}

    # Get back to the calendar for hour 2.
    sess.ensure(page)
    browser.open_court_reservation(page)
    browser.select_court_type(page, court_type)
    browser.navigate_to_date(page, target)

    sess.ensure(page)
    try:
        conf_b = browser.book_one_slot(page, court_b, hour_b)
    except browser.SlotUnavailable:
        log.warning("Hour 2 slot was taken between scan and booking")
        _mark_unavailable(availability, court_b, hour_b)
        notifier.send_partial_taken(target, court_a, hour_a, conf_a, court_b, hour_b)
        return {
            "status": "ok_partial",
            "court_type": court_type,
            "courts": [court_a],
            "hours": [hour_a],
            "confirmations": [conf_a],
        }
    except browser.CartCaptchaFailed:
        log.warning("CAPTCHA failed on hour 2")
        notifier.send_partial_captcha(target, court_a, hour_a, conf_a, court_b, hour_b)
        return {
            "status": "ok_partial",
            "court_type": court_type,
            "courts": [court_a],
            "hours": [hour_a],
            "confirmations": [conf_a],
        }

    return {
        "status": "ok_full",
        "court_type": court_type,
        "courts": [court_a, court_b] if court_a != court_b else [court_a],
        "hours": [hour_a, hour_b],
        "confirmations": [conf_a, conf_b],
    }


def _book_entry(page, target: date, entry: tuple,
                availability: dict[str, set[int]],
                sess: SessionContext) -> dict | None:
    """Try a single priority entry, exhausting all valid candidates within it
    before returning None (move on to next priority).
    """
    duration, start, court_type, same = entry
    courts = config.COURTS_BY_TYPE[court_type]

    sess.ensure(page)
    browser.select_court_type(page, court_type)
    browser.navigate_to_date(page, target)

    if duration == 1:
        for court in _candidates_one_hour(availability, courts, start):
            sess.ensure(page)
            try:
                conf = browser.book_one_slot(page, court, start)
            except browser.SlotUnavailable:
                log.info("Slot %s@%d unavailable on click — trying next candidate", court, start)
                _mark_unavailable(availability, court, start)
                continue
            except browser.CartCaptchaFailed:
                notifier.send_captcha_alert(target, court, start)
                return {"status": "captcha_no_booking"}
            return {
                "status": "ok_full",
                "court_type": court_type,
                "courts": [court],
                "hours": [start],
                "confirmations": [conf],
            }
        return None

    # 2-hour: try every valid pair in priority order; only fall through to
    # next priority when ALL pairs failed at hour 1.
    pairs = (
        _candidates_two_hour_same(availability, courts, start) if same
        else _candidates_two_hour_different(availability, courts, start)
    )
    for (a, b) in pairs:
        result = _try_two_hour_pair(page, target, court_type, a, start, b, start + 1, sess, availability)
        if result is None:
            log.info("Pair %s@%d + %s@%d unavailable — trying next pair", a, start, b, start + 1)
            continue
        return result
    return None


# ---------------------------------------------------------------------------
# Verification + recording
# ---------------------------------------------------------------------------


def _verify_and_record(page, target: date, result: dict, sess: SessionContext) -> None:
    courts = result["courts"]
    hours = result["hours"]
    confs = result["confirmations"]
    court_type = result["court_type"]

    try:
        sess.ensure(page)
        browser.open_my_reservations(page)
        all_found = True
        for i, h in enumerate(hours):
            c = courts[i] if i < len(courts) else courts[0]
            if not browser.verify_reservation(page, c, h, target):
                all_found = False
                break
        if not all_found:
            log.warning("Verification failed — sending warning email but NOT retrying")
            expected = []
            for i, h in enumerate(hours):
                c = courts[i] if i < len(courts) else courts[0]
                expected.append((c, h))
            notifier.send_verification_warning(target, expected)
    except Exception:
        log.exception("Could not run My Reservations verification — proceeding anyway")

    if len(hours) == 2:
        court_a = courts[0]
        court_b = courts[1] if len(courts) > 1 else courts[0]
        notifier.send_success_full(target, court_a, hours[0], confs[0], court_b, hours[1], confs[1])
    else:
        notifier.send_success_single(target, courts[0], hours[0], confs[0])

    try:
        dashboard.update_dashboard(target, court_type, courts, hours, confs)
    except Exception:
        log.exception("Dashboard update failed (booking already succeeded)")


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def main() -> int:
    setup_logging()
    load_dotenv(REPO_DIR / ".env")

    run_date = today()
    log.info("=== PPTC booking run starting at %s ===", datetime.now().isoformat(timespec="seconds"))
    log.info("Run date: %s (weekday=%d) TEST_MODE=%s MOCK_URL=%s",
             run_date.isoformat(), run_date.weekday(), config.TEST_MODE, config.MOCK_URL or "<none>")

    force = os.getenv("FORCE_RUN", "").strip() in ("1", "true", "yes")
    if not in_active_window(run_date) and not force:
        log.info("Outside active window (%s to %s) — exiting",
                 config.ACTIVE_START_DATE, config.ACTIVE_END_DATE)
        return 0
    if run_date.weekday() not in config.RUN_WEEKDAYS and not force:
        log.info("Not a Saturday/Sunday — exiting")
        return 0
    if force:
        log.info("FORCE_RUN active — bypassing weekday/window guards")

    target = target_date_for(run_date)
    log.info("Target date: %s (%s)", target.isoformat(), target.strftime("%a"))

    email = os.getenv("PPTC_EMAIL")
    password = os.getenv("PPTC_PASSWORD")
    if not email or not password:
        log.error("PPTC credentials missing — cannot continue")
        notifier.send_error(target, RuntimeError("PPTC_EMAIL/PPTC_PASSWORD not set"),
                            context="startup")
        test_capture.record_outcome(None, "error_abort")
        return 2

    sess = SessionContext(email, password)
    final_result = "error_abort"
    priority_hit: int | None = None

    try:
        with browser.launch_browser() as (page, _ctx):
            browser.login(page, email, password)
            availability = _scan_all(page, target, sess)

            if not any(availability.values()):
                log.info("No availability anywhere — sending no-slots email")
                notifier.send_no_slots(target, availability)
                final_result = "no_slots"
                test_capture.record_outcome(None, final_result)
                return 0

            for idx, entry in enumerate(config.PRIORITY_LIST, start=1):
                log.info("=== Trying priority #%d: %s ===", idx, entry)
                result = _book_entry(page, target, entry, availability, sess)
                if result is None:
                    continue
                if result["status"] == "captcha_no_booking":
                    log.error("CAPTCHA failed before any hour was booked — aborting")
                    final_result = "error_abort"
                    priority_hit = idx
                    test_capture.record_outcome(priority_hit, final_result)
                    return 3
                _verify_and_record(page, target, result, sess)
                priority_hit = idx
                final_result = "success_2h" if len(result["hours"]) == 2 else "success_1h"
                log.info("Done. Status=%s priority=%d", result["status"], idx)
                test_capture.record_outcome(priority_hit, final_result)
                return 0

            log.info("Exhausted priority list with no successful booking")
            notifier.send_no_slots(target, availability)
            final_result = "no_slots"
            test_capture.record_outcome(None, final_result)
            return 0

    except browser.LoginFailed as exc:
        log.exception("Login failed")
        notifier.send_error(target, exc, context="login")
        test_capture.record_outcome(priority_hit, final_result)
        return 4
    except Exception as exc:  # noqa: BLE001 — top-level catch-all per spec
        log.exception("Unhandled exception in main loop")
        notifier.send_error(target, exc, context="main")
        test_capture.record_error(str(exc))
        test_capture.record_outcome(priority_hit, final_result)
        return 1


if __name__ == "__main__":
    sys.exit(main())
