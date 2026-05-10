"""Email notifications via Gmail SMTP (SSL on port 465).

In TEST_MODE, real SMTP is suppressed and email metadata is captured to a
local file for the test runner to inspect.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import date
from email.mime.text import MIMEText
from typing import Iterable

import config
import test_capture

log = logging.getLogger(__name__)


def _send(email_type: str, subject: str, body: str) -> None:
    """Send a plain-text email. Errors are logged but do not raise."""
    if config.TEST_MODE:
        test_capture.record_email(email_type, subject, body)
        return

    sender = os.getenv("NOTIFY_EMAIL_FROM")
    password = os.getenv("NOTIFY_EMAIL_PASSWORD")
    recipient = os.getenv("NOTIFY_EMAIL")
    if not (sender and password and recipient):
        log.error("Email credentials missing; cannot send notification: %s", subject)
        return

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [recipient], msg.as_string())
        log.info("Email sent: %s", subject)
    except Exception as exc:
        log.exception("Failed to send email '%s': %s", subject, exc)


def _format_day(d: date) -> str:
    return d.strftime("%a")  # e.g. "Sat"


def _format_date(d: date) -> str:
    return d.strftime("%b %-d, %Y")  # e.g. "May 17, 2026"


# --- Public helpers ---------------------------------------------------------


def send_success_full(target_date: date, court_a: str, hour_a: int,
                      conf_a: str, court_b: str, hour_b: int, conf_b: str) -> None:
    """Both hours of a 2-hour block were booked successfully."""
    same = court_a == court_b
    courts_label = court_a.upper() if same else f"{court_a.upper()} + {court_b.upper()}"
    time_label = f"{hour_a:02d}:00–{hour_b + 1:02d}:00"
    subject = f"🎾 Booked! {_format_day(target_date)} {_format_date(target_date)} {time_label} {courts_label}"
    body = (
        f"Successfully booked 2 hours at PPTC.\n\n"
        f"Date: {_format_day(target_date)} {_format_date(target_date)}\n"
        f"Court(s): {courts_label}\n"
        f"Time: {time_label}\n\n"
        f"Hour 1: Court {court_a.upper()} {hour_a:02d}:00–{hour_a+1:02d}:00\n"
        f"  Confirmation #: {conf_a}\n\n"
        f"Hour 2: Court {court_b.upper()} {hour_b:02d}:00–{hour_b+1:02d}:00\n"
        f"  Confirmation #: {conf_b}\n\n"
        f"Dashboard: {config.GITHUB_PAGES_URL}\n"
    )
    _send("success_2h", subject, body)


def send_success_single(target_date: date, court: str, hour: int, conf: str) -> None:
    """A single 1-hour slot was booked from the priority list."""
    time_label = f"{hour:02d}:00–{hour+1:02d}:00"
    subject = f"🎾 Booked! {_format_day(target_date)} {_format_date(target_date)} {time_label} {court.upper()}"
    body = (
        f"Successfully booked 1 hour at PPTC.\n\n"
        f"Date: {_format_day(target_date)} {_format_date(target_date)}\n"
        f"Court: {court.upper()}\n"
        f"Time: {time_label}\n"
        f"Confirmation #: {conf}\n\n"
        f"Dashboard: {config.GITHUB_PAGES_URL}\n"
    )
    _send("success_1h", subject, body)


def send_partial_captcha(target_date: date, booked_court: str, booked_hour: int,
                         booked_conf: str, missed_court: str, missed_hour: int) -> None:
    """Hour 1 booked successfully, but CAPTCHA failed on hour 2."""
    subject = f"🎾 Partially Booked — {_format_day(target_date)} {_format_date(target_date)}"
    body = (
        f"Booked Court {booked_court.upper()} {booked_hour:02d}:00–{booked_hour+1:02d}:00 "
        f"(confirmation {booked_conf}).\n\n"
        f"Could not book Court {missed_court.upper()} {missed_hour:02d}:00–{missed_hour+1:02d}:00 "
        f"— CAPTCHA failed. Book this hour manually NOW.\n\n"
        f"Login: {config.LOGIN_URL}\n"
    )
    _send("partial_captcha", subject, body)


def send_partial_taken(target_date: date, booked_court: str, booked_hour: int,
                       booked_conf: str, missed_court: str, missed_hour: int) -> None:
    """Hour 1 booked, hour 2 was claimed by someone else mid-flow."""
    subject = f"🎾 Partially Booked — {_format_day(target_date)} {_format_date(target_date)}"
    body = (
        f"Booked Court {booked_court.upper()} {booked_hour:02d}:00–{booked_hour+1:02d}:00 only "
        f"(confirmation {booked_conf}).\n\n"
        f"Court {missed_court.upper()} {missed_hour:02d}:00–{missed_hour+1:02d}:00 was taken "
        f"before we could book it. No replacement attempted.\n\n"
        f"Dashboard: {config.GITHUB_PAGES_URL}\n"
    )
    _send("partial_taken", subject, body)


def send_captcha_alert(target_date: date, court: str, hour: int) -> None:
    """CAPTCHA failed before any booking succeeded — user must book manually."""
    subject = "🎾 CAPTCHA — book manually NOW"
    body = (
        f"CapSolver was attempted and failed for the slot below.\n\n"
        f"Date: {_format_day(target_date)} {_format_date(target_date)}\n"
        f"Court: {court.upper()}\n"
        f"Time: {hour:02d}:00–{hour+1:02d}:00\n\n"
        f"Login: {config.LOGIN_URL}\n"
        f"Grab this slot manually as soon as possible.\n"
    )
    _send("captcha_alert", subject, body)


def send_no_slots(target_date: date, availability: dict) -> None:
    """Every priority entry was unavailable. Dump full availability."""
    subject = f"🎾 No slots available — {_format_day(target_date)} {_format_date(target_date)}"
    lines = [f"No bookable slots found for {_format_date(target_date)}.\n", "Full availability scan:"]
    for court in sorted(availability.keys()):
        hours = sorted(availability[court])
        if hours:
            ranges = ", ".join(f"{h:02d}:00–{h+1:02d}:00" for h in hours)
        else:
            ranges = "(no open hours)"
        lines.append(f"  Court {court.upper()}: {ranges}")
    _send("no_slots", subject, "\n".join(lines))


def send_error(target_date: date, exc: BaseException, context: str = "") -> None:
    """Top-level exception caught — alert via email."""
    subject = f"🎾 PPTC error — {_format_day(target_date)} {_format_date(target_date)}"
    import traceback
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    body = (
        f"The PPTC booking run crashed.\n\n"
        f"Context: {context or '(none)'}\n\n"
        f"Exception:\n{tb}\n"
    )
    _send("error", subject, body)


def send_verification_warning(target_date: date, expected: Iterable[tuple]) -> None:
    """Booking succeeded per the cart, but My Reservations didn't show it."""
    subject = "🎾 PPTC warning — booking confirmation could not be verified"
    expected_str = "\n".join(
        f"  Court {c.upper()} {h:02d}:00–{h+1:02d}:00" for c, h in expected
    )
    body = (
        f"The booking flow completed for {_format_date(target_date)} "
        f"but the booking could not be verified on My Reservations.\n\n"
        f"Expected to find:\n{expected_str}\n\n"
        f"Please check the portal manually. No retry was attempted, "
        f"to avoid double-charging.\n"
    )
    _send("verification_warning", subject, body)
