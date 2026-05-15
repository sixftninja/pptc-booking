"""Configuration constants for the PPTC court booking system.

Selectors live here so they can be adjusted in one place after the first
real run against the live site reveals the actual HTML structure.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Load .env once, at config import time, so any module that imports config
# can read env-derived values without ordering concerns.
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- Site URLs ---------------------------------------------------------------
# Real PPTC member portal. Override via MOCK_URL (e.g. "http://localhost:5000")
# in .env to point the booker at the local simulator instead.
_REAL_SITE_BASE = "https://prospectpark.aptussoft.com"
_REAL_LOGIN_URL = f"{_REAL_SITE_BASE}/Member"

MOCK_URL = os.getenv("MOCK_URL", "").rstrip("/")
if MOCK_URL:
    SITE_BASE_URL = MOCK_URL
    LOGIN_URL = MOCK_URL if MOCK_URL.endswith("/Member") else f"{MOCK_URL}/Member"
    SITE_BASE_URL = LOGIN_URL.rsplit("/Member", 1)[0]
else:
    SITE_BASE_URL = _REAL_SITE_BASE
    LOGIN_URL = _REAL_LOGIN_URL

# CapSolver. Real endpoint is api.capsolver.com; override for tests.
# Use `or` (not the getenv default) so an empty string in .env still falls
# through to the real URL.
CAPSOLVER_API_URL = (os.getenv("CAPSOLVER_MOCK_URL") or "https://api.capsolver.com").rstrip("/")

# Test mode: when set, suppress real SMTP and real git push, write metadata
# to TEST_OUTPUT_DIR instead. Used by the simulator's runner.
TEST_MODE = os.getenv("TEST_MODE", "").strip() in ("1", "true", "True", "yes")
TEST_OUTPUT_DIR = Path(__file__).resolve().parent / "simulator" / "test_results"

# --- Active booking window ---------------------------------------------------
# Process exits immediately if run outside this range.
# First run that books a real outdoor day: May 10, 2026 (books May 17).
# Final run: September 27, 2026 (books October 4 — last outdoor day).
ACTIVE_START_DATE = date(2026, 5, 10)
ACTIVE_END_DATE = date(2026, 9, 27)

# Days on which a booking run is allowed (Mon=0 ... Sun=6).
# Saturday=5 and Sunday=6 in Python's weekday() numbering.
RUN_WEEKDAYS = {5, 6}

# --- Court configuration -----------------------------------------------------
# Hard courts: no order preference, both equally good.
HARD_COURTS = ["5a", "4a"]
# Clay courts in priority order. 6b is intentionally excluded.
CLAY_COURTS = ["3a", "2a", "1a", "4b", "5b"]
EXCLUDED_COURTS = {"6b"}

# 4b and 5b are "permit courts" — bookable only 7am–7pm. Never attempt to
# book them for slots that START at 19:00 (7pm) or later.
PERMIT_COURTS = {"4b", "5b"}
PERMIT_COURT_LATEST_START_HOUR = 18  # last allowed start hour for permit courts

COURTS_BY_TYPE = {
    "hard": HARD_COURTS,
    "clay": CLAY_COURTS,
}

# Type dropdown labels on the Court Reservation page.
TYPE_LABEL_HARD = "Hard"
TYPE_LABEL_CLAY = "Clay"

# Attendee name used in the booking modal's Attendee dropdown — must match
# the dropdown label exactly. Comes from .env.
ATTENDEE_NAME = os.getenv("PPTC_ATTENDEE_NAME", "")
# Item Details is pre-selected by the site for each slot. The booker MUST NOT
# touch this dropdown — leave whatever the site has chosen.

# --- Booking attempt timing --------------------------------------------------
DEFAULT_TIMEOUT_MS = 15_000
SHORT_TIMEOUT_MS = 10_000
CAPTCHA_TIMEOUT_S = 60
RECAPTCHA_CHECKBOX_WAIT_S = 3

# Realistic Mac Chrome user-agent (per spec).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# --- Selectors ---------------------------------------------------------------
# These are best-guess selectors based on the spec. They will likely need
# minor tweaks after the first live test run on May 10, 2026.
SELECTORS = {
    # Login page
    "login_email":       '#email, input[name="email"]',
    "login_password":    '#password, input[name="password"]',
    "login_submit":      '#btnSignIn, button:has-text("Sign In")',
    "login_error":       '.validation-summary-errors, .alert-danger, .field-validation-error, .msgBox',

    # Left navigation
    "nav_programs":      'a:has-text("Programs & Services"), button:has-text("Programs & Services")',
    "nav_court_res":     'a:has-text("Court Reservation")',
    "nav_account":       'a:has-text("Account Activity"), button:has-text("Account Activity")',
    "nav_my_reservations": 'a:has-text("My Reservations")',

    # Court Reservation page (FullCalendar resource-day view)
    "type_dropdown":     '#Resource',
    "calendar_next":     '.fc-header-left .fc-button-next',
    "calendar_prev":     '.fc-header-left .fc-button-prev',
    "calendar_date_label": '.fc-header-title h2, .fc-header-title',

    # Booking modal
    # NOTE: there is intentionally no `modal_item_details` selector — the site
    # pre-selects the correct value and the booker must never touch it.
    "modal":              '.modal.show, .modal[style*="display: block"], div[role="dialog"]',
    "modal_attendee":     'select[name*="ttendee"], select#Attendee',
    "modal_notes":        'textarea[name*="otes"], textarea#ApptNotes',
    "modal_waiver":       'input[type="checkbox"][name*="aiver"], input[type="checkbox"]#Waiver, label:has-text("I have read and understand") input[type="checkbox"]',
    "modal_go":           'button:has-text("Go"), input[type="submit"][value="Go"]',
    "modal_cancel":       'button:has-text("Cancel")',

    # Post-Go restriction popups (book denied by server)
    "restriction_dialog":     '.modal.show, div[role="dialog"], .ui-dialog',
    "restriction_dialog_ok":  'button:has-text("Ok"), button:has-text("OK")',

    # Cart / payment
    "cart_continue_shopping": 'button:has-text("Continue Shopping"), a:has-text("Continue Shopping")',
    "cart_clear":             'button:has-text("Clear Cart")',
    "cart_submit":            'button:has-text("Submit"), button:has-text("Pay"), button:has-text("Complete"), input[type="submit"]',
    "recaptcha_iframe":       'iframe[src*="recaptcha"], iframe[title*="reCAPTCHA" i]',
    "recaptcha_anchor_checkbox": '#recaptcha-anchor',
    "recaptcha_challenge_iframe": 'iframe[title*="challenge" i]',

    # Confirmation
    "confirmation_text":  'text=/transaction has been approved/i',
    "confirmation_popup_ok": 'button:has-text("Ok"), button:has-text("OK")',
    "confirmation_number_text": 'text=/confirmation number/i',
}

# --- Priority list (44 entries) ----------------------------------------------
# Tuple format:
#   (duration_hours, start_hour, court_type, same_court_bool)
# For 1-hour entries the same_court flag is omitted (None).
#
# duration: 1 or 2 hours
# start_hour: hour of day to begin (24h clock)
# court_type: "hard" or "clay"
# same_court: True = both hours on same court; False = different courts
PRIORITY_LIST = [
    # ----- Steps 1-12: prime times (9, 10, 11) -- hard first then clay -----
    (2,  9, "hard", True),  (2,  9, "hard", False),   # 1, 2
    (2, 10, "hard", True),  (2, 10, "hard", False),   # 3, 4
    (2, 11, "hard", True),  (2, 11, "hard", False),   # 5, 6
    (2,  9, "clay", True),  (2,  9, "clay", False),   # 7, 8
    (2, 10, "clay", True),  (2, 10, "clay", False),   # 9, 10
    (2, 11, "clay", True),  (2, 11, "clay", False),   # 11, 12

    # ----- Steps 13-28: later times (12, 13, 14, 15) -- alternating type --
    (2, 12, "hard", True),  (2, 12, "hard", False),   # 13, 14
    (2, 12, "clay", True),  (2, 12, "clay", False),   # 15, 16
    (2, 13, "hard", True),  (2, 13, "hard", False),   # 17, 18
    (2, 13, "clay", True),  (2, 13, "clay", False),   # 19, 20
    (2, 14, "hard", True),  (2, 14, "hard", False),   # 21, 22
    (2, 14, "clay", True),  (2, 14, "clay", False),   # 23, 24
    (2, 15, "hard", True),  (2, 15, "hard", False),   # 25, 26
    (2, 15, "clay", True),  (2, 15, "clay", False),   # 27, 28

    # ----- Steps 29-36: 1-hour hard, earliest first ----------------------
    (1,  9, "hard", None), (1, 10, "hard", None), (1, 11, "hard", None),
    (1, 12, "hard", None), (1, 13, "hard", None), (1, 14, "hard", None),
    (1, 15, "hard", None), (1, 16, "hard", None),

    # ----- Steps 37-44: 1-hour clay, earliest first ----------------------
    (1,  9, "clay", None), (1, 10, "clay", None), (1, 11, "clay", None),
    (1, 12, "clay", None), (1, 13, "clay", None), (1, 14, "clay", None),
    (1, 15, "clay", None), (1, 16, "clay", None),
]

assert len(PRIORITY_LIST) == 44, f"Priority list must have 44 entries, has {len(PRIORITY_LIST)}"

# --- Dashboard / GitHub ------------------------------------------------------
GITHUB_PAGES_BRANCH = "gh-pages"
GITHUB_PAGES_URL = "https://sixftninja.github.io/pptc-booking"
DASHBOARD_DATA_FILE = "bookings.json"
DASHBOARD_HTML_FILE = "index.html"
DASHBOARD_TITLE = "PPTC Court Bookings — 2026 Outdoor Season"
DASHBOARD_SEASON_LABEL = "May 17 – Oct 4, 2026"
PPTC_GREEN = "#4a7c59"

# --- Email -------------------------------------------------------------------
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL


def format_hour_range(start_hour: int, duration: int) -> str:
    """Return a human-readable time range like '09:00–11:00'."""
    return f"{start_hour:02d}:00–{start_hour + duration:02d}:00"
