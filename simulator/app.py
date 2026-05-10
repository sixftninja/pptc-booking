"""Flask app — PPTC member portal simulator.

Routes (front-of-house):
    GET  /                              -> redirect to /Member
    GET  /Member                        -> login page
    POST /Member                        -> login submit
    GET  /Member/Dashboard              -> dashboard (left nav)
    GET  /Member/CourtReservation       -> calendar
    POST /Member/CourtReservation/book  -> open booking modal (returns JSON)
    POST /Member/Cart                   -> cart submit / payment
    GET  /Member/Cart                   -> cart page (after modal Go)
    GET  /Member/Confirmation           -> confirmation page (popup served inline)
    GET  /Member/MyReservations         -> reservation list

Routes (admin, only when FLASK_ENV=testing):
    POST /admin/set-scenario            body: {"scenario": "01_..."}
    POST /admin/reset                   reset state
    GET  /admin/status                  current scenario + state snapshot
    POST /admin/finish                  flush instrumentation to disk

Routes (CapSolver mock, used when CAPSOLVER_MOCK_URL points here):
    POST /capsolver-mock/createTask
    POST /capsolver-mock/getTaskResult
"""

from __future__ import annotations

import logging
import os
import random
import string
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, abort, jsonify, redirect, render_template, request,
    session as flask_session, url_for,
)

import captcha as cap
import instrumentation as instr
from state import STATE, TARGET_DATE_LABEL, TARGET_DATE_SHORT

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s sim | %(message)s")
log = logging.getLogger("sim")

app = Flask(__name__,
            template_folder=str(HERE / "templates"),
            static_folder=str(HERE / "static"))
app.secret_key = os.getenv("SIMULATOR_SECRET", "pptc-simulator-secret")

# Load initial scenario from .env so single-scenario manual testing works
# without invoking /admin/set-scenario first.
_INITIAL_SCENARIO = os.getenv("ACTIVE_SCENARIO", "01_full_availability_checkbox")
try:
    STATE.load_scenario(_INITIAL_SCENARIO)
    instr.INSTR.start(_INITIAL_SCENARIO,
                      int(_INITIAL_SCENARIO.split("_", 1)[0]) if _INITIAL_SCENARIO[:2].isdigit() else 0)
    log.info("Initial scenario loaded: %s", _INITIAL_SCENARIO)
except Exception as exc:
    log.exception("Could not load initial scenario %s: %s", _INITIAL_SCENARIO, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_testing() -> bool:
    return os.getenv("FLASK_ENV", "").lower() in ("testing", "test", "development")


def _delay(key: str) -> None:
    """Sleep server-side per scenario response_delays_ms."""
    delays = STATE.scenario.get("response_delays_ms") or {}
    ms = delays.get(key, 0)
    if ms:
        time.sleep(ms / 1000.0)


def _captcha_mode() -> str:
    return STATE.scenario.get("captcha_mode") or os.getenv("CAPTCHA_MODE", "test")


def _logged_in() -> bool:
    if STATE.session_invalidated:
        return False
    return bool(flask_session.get("authed"))


def _require_login_or_redirect():
    """If not logged in (or session was invalidated), bounce to /Member."""
    if not _logged_in():
        return redirect("/Member")
    return None


def _gen_confirmation() -> str:
    return "TEST-" + "".join(random.choices(string.digits, k=6))


# ---------------------------------------------------------------------------
# Front-of-house routes
# ---------------------------------------------------------------------------


@app.route("/", methods=["GET"])
def root():
    return redirect("/Member")


@app.route("/Member", methods=["GET", "POST"])
def member_login():
    if request.method == "POST":
        with instr.TimedBlock("login_duration"):
            _delay("login")
            email = (request.form.get("email") or "").strip()
            password = (request.form.get("password") or "").strip()
            if not email or not password:
                return render_template("login.html",
                                       error="Email and password required",
                                       sitekey=cap.sitekey_for_mode(_captcha_mode())
                                                if STATE.scenario.get("captcha_on_login") else "",
                                       widget=STATE.scenario.get("captcha_on_login", False)
                                       )
            if STATE.scenario.get("captcha_on_login"):
                token = request.form.get("g-recaptcha-response", "")
                if cap.token_required(_captcha_mode()) and not token:
                    return render_template("login.html",
                                           error="reCAPTCHA required",
                                           sitekey=cap.sitekey_for_mode(_captcha_mode()),
                                           widget=True)
            flask_session["authed"] = True
            flask_session["session_id"] = str(uuid.uuid4())
            STATE.session_invalidated = False
            instr.INSTR.record_event("login", email=email)

            # session.expire_after_login: bounce on first nav.
            sess_cfg = STATE.scenario.get("session") or {}
            if sess_cfg.get("expire_after_login"):
                STATE.invalidate_session()

        return redirect("/Member/Dashboard")

    sitekey = cap.sitekey_for_mode(_captcha_mode()) if STATE.scenario.get("captcha_on_login") else ""
    return render_template("login.html",
                           error=None,
                           sitekey=sitekey,
                           widget=bool(STATE.scenario.get("captcha_on_login")))


@app.route("/Member/Dashboard", methods=["GET"])
def dashboard():
    r = _require_login_or_redirect()
    if r is not None:
        return r
    return render_template("dashboard.html")


@app.route("/Member/CourtReservation", methods=["GET"])
def court_reservation():
    r = _require_login_or_redirect()
    if r is not None:
        return r
    with instr.TimedBlock("calendar_load_duration"):
        _delay("calendar_load")
        court_type = request.args.get("type", "Hard")
        if court_type not in ("Hard", "Clay"):
            court_type = "Hard"
        # Type-switch delay if the previous request was different.
        prev = flask_session.get("last_type")
        if prev and prev != court_type:
            with instr.TimedBlock("type_switch_duration"):
                _delay("type_dropdown_switch")
        flask_session["last_type"] = court_type

        courts = STATE.courts_for_type(court_type)
        # Build the time-row grid: hours 6..21
        hours = list(range(6, 22))
        grid = []
        for h in hours:
            row = []
            for court in courts:
                available = STATE.is_available(court_type, court, h)
                row.append({
                    "court": court,
                    "hour": h,
                    "available": available,
                })
            grid.append({"hour": h, "row": row})
    return render_template("court_reservation.html",
                           court_type=court_type,
                           courts=courts,
                           grid=grid,
                           date_label=TARGET_DATE_LABEL)


@app.route("/Member/CourtReservation/modal", methods=["GET"])
def booking_modal():
    """Open the booking modal for a given (court_type, court, hour)."""
    r = _require_login_or_redirect()
    if r is not None:
        return r
    with instr.TimedBlock("modal_open_duration"):
        _delay("modal_open")
        court_type = request.args.get("type")
        court = request.args.get("court")
        hour_s = request.args.get("hour", "")
        try:
            hour = int(hour_s)
        except ValueError:
            return ("Bad hour", 400)
        # TOCTOU: server says nope.
        rc = STATE.scenario.get("race_condition") or {}
        if rc.get("enabled") and rc.get("type") == "toctou":
            tcourt = rc.get("trigger_after_court")
            thour = rc.get("trigger_after_hour")
            if court == tcourt and hour == thour:
                return ("Slot no longer available", 409)
        if not STATE.is_available(court_type, court, hour):
            return ("Slot no longer available", 409)
        flask_session["pending_booking"] = {
            "court_type": court_type,
            "court": court,
            "hour": hour,
        }
    return render_template("booking_modal.html",
                           court=court, hour=hour,
                           court_type=court_type)


@app.route("/Member/Cart", methods=["GET", "POST"])
def cart():
    r = _require_login_or_redirect()
    if r is not None:
        return r

    if request.method == "POST":
        # Booker hit Submit on the cart page.
        return _process_payment()

    # GET — booker landed on cart from modal "Go".
    fi = STATE.scenario.get("fault_injection") or {}
    if fi.get("cart_hang_first_load"):
        n = STATE.increment_cart_post()
        if n == 1:
            time.sleep(30)
            return ("Gateway Timeout", 504)
    with instr.TimedBlock("cart_load_duration"):
        _delay("cart_load")
    pending = flask_session.get("pending_booking") or {}
    sitekey = cap.sitekey_for_mode(_captcha_mode()) if STATE.scenario.get("captcha_on_booking") else ""
    return render_template("cart.html",
                           pending=pending,
                           sitekey=sitekey,
                           widget=bool(STATE.scenario.get("captcha_on_booking")),
                           amount="84.00")


def _process_payment():
    """Verify reCAPTCHA token presence, hardcode payment success, return confirmation."""
    pending = flask_session.get("pending_booking") or {}
    if not pending:
        return ("No pending booking", 400)

    fi = STATE.scenario.get("fault_injection") or {}

    # capsolver_invalid_key is enforced by the CapSolver mock endpoint —
    # this route doesn't need to do anything special; if the booker even
    # got here, it solved the captcha.

    if STATE.scenario.get("captcha_on_booking"):
        token = request.form.get("g-recaptcha-response", "")
        if cap.token_required(_captcha_mode()) and not token:
            return ("reCAPTCHA required", 400)

    if fi.get("confirmation_never_loads"):
        # Hang the connection forever.
        time.sleep(120)
        return ("Gateway Timeout", 504)

    with instr.TimedBlock("confirmation_duration"):
        _delay("confirmation")
        conf = _gen_confirmation()
        STATE.mark_booked(
            pending["court_type"], pending["court"], pending["hour"],
            conf, attendee="Anand Altekar",
        )
        STATE.maybe_invalidate_after_booking()
        STATE.trigger_race_after_booking(pending["court"], pending["hour"])
        instr.INSTR.record_booking(
            court=pending["court"], hour=pending["hour"],
            court_type=pending["court_type"],
            confirmation=conf,
        )
    flask_session.pop("pending_booking", None)
    return render_template("confirmation.html", confirmation=conf)


@app.route("/Member/MyReservations", methods=["GET"])
def my_reservations():
    r = _require_login_or_redirect()
    if r is not None:
        return r
    with instr.TimedBlock("my_reservations_check_duration"):
        _delay("my_reservations_load")
        fi = STATE.scenario.get("fault_injection") or {}
        if fi.get("my_reservations_hide_booking"):
            bookings_to_show: list[dict] = []
        else:
            bookings_to_show = list(STATE.bookings)
    return render_template("my_reservations.html",
                           bookings=bookings_to_show,
                           date_short=TARGET_DATE_SHORT,
                           target_date_label=TARGET_DATE_LABEL)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


def _require_localhost_and_testing():
    if not _is_testing():
        abort(403)
    addr = request.remote_addr or ""
    if addr not in ("127.0.0.1", "::1", "localhost"):
        abort(403)


@app.route("/admin/set-scenario", methods=["POST"])
def admin_set_scenario():
    _require_localhost_and_testing()
    body = request.get_json(silent=True) or {}
    name = body.get("scenario", "").strip()
    if not name:
        return jsonify({"error": "scenario required"}), 400
    STATE.load_scenario(name)
    flask_session.clear()
    sn = int(name.split("_", 1)[0]) if name[:2].isdigit() else 0
    instr.INSTR.start(name, sn)
    log.info("Scenario set: %s", name)
    return jsonify({"ok": True, "scenario": name})


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    _require_localhost_and_testing()
    STATE.reset()
    flask_session.clear()
    log.info("State reset for scenario %s", STATE.scenario_name)
    return jsonify({"ok": True})


@app.route("/admin/status", methods=["GET"])
def admin_status():
    _require_localhost_and_testing()
    return jsonify(STATE.snapshot())


@app.route("/admin/finish", methods=["POST"])
def admin_finish():
    """Stop the run timer and flush instrumentation to disk."""
    _require_localhost_and_testing()
    instr.INSTR.stop()
    path = instr.INSTR.write()
    return jsonify({"ok": True, "path": str(path)})


# ---------------------------------------------------------------------------
# CapSolver mock
# ---------------------------------------------------------------------------


@app.route("/capsolver-mock/createTask", methods=["POST"])
def capsolver_create_task():
    fi = STATE.scenario.get("fault_injection") or {}
    if fi.get("capsolver_invalid_key"):
        return jsonify({"errorId": 1, "errorCode": "ERROR_KEY_DOES_NOT_EXIST",
                        "errorDescription": "Mocked: invalid key"}), 401
    body = request.get_json(silent=True) or {}
    task_id = "mock-" + uuid.uuid4().hex[:12]
    flask_session["mock_capsolver_task"] = {
        "id": task_id,
        "started_at": time.time(),
        "site_key": (body.get("task") or {}).get("websiteKey", ""),
    }
    return jsonify({"errorId": 0, "taskId": task_id})


@app.route("/capsolver-mock/getTaskResult", methods=["POST"])
def capsolver_get_result():
    fi = STATE.scenario.get("fault_injection") or {}
    if fi.get("capsolver_invalid_key"):
        return jsonify({"errorId": 1, "errorCode": "ERROR_KEY_DOES_NOT_EXIST",
                        "errorDescription": "Mocked: invalid key"}), 401

    body = request.get_json(silent=True) or {}
    task = flask_session.get("mock_capsolver_task") or {}
    if not task or task.get("id") != body.get("taskId"):
        return jsonify({"errorId": 1, "errorCode": "ERROR_NO_TASK_ID",
                        "errorDescription": "Unknown task"}), 400

    if fi.get("capsolver_timeout"):
        # Always processing; the booker will eventually hit its 60s budget.
        return jsonify({"errorId": 0, "status": "processing"})

    elapsed = time.time() - float(task.get("started_at") or time.time())
    # Simulate a realistic solve time: 3-6 seconds in test, 8-15 in forced.
    mode = _captcha_mode()
    needed = 3.0 if mode == "test" else 6.0
    if elapsed < needed:
        return jsonify({"errorId": 0, "status": "processing"})
    return jsonify({
        "errorId": 0,
        "status": "ready",
        "solution": {"gRecaptchaResponse": "MOCK_TOKEN_" + uuid.uuid4().hex},
    })


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.getenv("SIMULATOR_PORT", "5000"))
    # Threaded=True so a hanging request (e.g. cart_hang_first_load) doesn't
    # block subsequent admin endpoints.
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
