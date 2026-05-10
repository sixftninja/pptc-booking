"""Simulator state.

Holds the loaded scenario, current bookings, and per-process counters used
to inject faults (e.g. cart_hang_first_load fires only on the first POST).
Hot-reloaded by /admin/set-scenario without a Flask restart.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
SCENARIOS_DIR = HERE / "scenarios"

# The simulator anchors to "today's target" = May 17, 2026 in all tests.
TARGET_DATE = date(2026, 5, 17)
TARGET_DATE_LABEL = TARGET_DATE.strftime("%A, %B %-d, %Y")  # "Sunday, May 17, 2026"
TARGET_DATE_SHORT = TARGET_DATE.strftime("%-m/%-d/%Y")       # "5/17/2026"

# Always-excluded court (per spec).
EXCLUDED_COURT = "6b"

_lock = threading.Lock()


class SimulatorState:
    def __init__(self) -> None:
        self.scenario_name: str = ""
        self.scenario: dict = {}
        # Mutable copy that records what's been booked or removed during a run.
        self.availability: dict[str, dict[str, list[int]]] = {}
        # bookings: list of {court, hour, confirmation_number, attendee, type, time}
        self.bookings: list[dict] = []
        # Counters used for fault injection / race triggers.
        self.cart_post_count: int = 0
        self.bookings_completed: int = 0
        self.session_invalidated: bool = False

    # ---- scenario loading -------------------------------------------------

    def load_scenario(self, name: str) -> None:
        path = SCENARIOS_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"scenario file not found: {path}")
        scenario = json.loads(path.read_text())
        with _lock:
            self.scenario_name = name
            self.scenario = scenario
            self.reset_locked()

    def reset(self) -> None:
        with _lock:
            self.reset_locked()

    def reset_locked(self) -> None:
        # availability — deep copy so mutations don't affect the source JSON.
        avail = copy.deepcopy(self.scenario.get("availability", {}))
        avail.setdefault("hard", {})
        avail.setdefault("clay", {})
        avail["clay"]["6b"] = []  # always.
        self.availability = avail
        self.bookings = []
        self.cart_post_count = 0
        self.bookings_completed = 0
        self.session_invalidated = False

    # ---- queries -----------------------------------------------------------

    def courts_for_type(self, court_type: str) -> list[str]:
        if court_type == "Hard" or court_type == "hard":
            return ["5a", "4a"]
        if court_type == "Clay" or court_type == "clay":
            return ["3a", "2a", "1a", "4b", "5b", "6b"]
        return []

    def hours_for(self, court_type: str, court: str) -> list[int]:
        bucket = self.availability.get(court_type.lower(), {})
        return list(bucket.get(court, []))

    def is_available(self, court_type: str, court: str, hour: int) -> bool:
        if court == EXCLUDED_COURT:
            # The spec only excludes 6b for the booker, but the simulator
            # serves it as always reserved. Honor that.
            return False
        return hour in self.hours_for(court_type, court)

    # ---- mutations ---------------------------------------------------------

    def mark_booked(self, court_type: str, court: str, hour: int,
                    confirmation: str, attendee: str) -> None:
        with _lock:
            bucket = self.availability.setdefault(court_type.lower(), {})
            hrs = list(bucket.get(court, []))
            if hour in hrs:
                hrs.remove(hour)
            bucket[court] = hrs
            self.bookings.append({
                "court": court,
                "court_type": court_type.lower(),
                "hour": hour,
                "confirmation": confirmation,
                "attendee": attendee,
            })
            self.bookings_completed += 1

    def remove_hours(self, court_type: str, court: str, hours: list[int]) -> None:
        with _lock:
            bucket = self.availability.setdefault(court_type.lower(), {})
            existing = list(bucket.get(court, []))
            bucket[court] = [h for h in existing if h not in hours]

    def trigger_race_after_booking(self, court_just_booked: str, hour_just_booked: int) -> None:
        """Apply the race_condition rule (if any) right after a booking commits."""
        rc = self.scenario.get("race_condition") or {}
        if not rc.get("enabled"):
            return
        if rc.get("type") != "post_booking_remove":
            return
        if rc.get("trigger_after_court") != court_just_booked:
            return
        if rc.get("trigger_after_hour") != hour_just_booked:
            return
        court = rc.get("mark_unavailable_court")
        hours = rc.get("mark_unavailable_hours") or []
        # mark_unavailable_court can be a single string or list (rules support both).
        if isinstance(court, str):
            self.remove_hours(rc.get("mark_court_type", "hard"), court, hours)
        elif isinstance(court, list):
            for c in court:
                self.remove_hours(rc.get("mark_court_type", "hard"), c, hours)

    def increment_cart_post(self) -> int:
        with _lock:
            self.cart_post_count += 1
            return self.cart_post_count

    def invalidate_session(self) -> None:
        with _lock:
            self.session_invalidated = True

    def maybe_invalidate_after_booking(self) -> None:
        sess_cfg = self.scenario.get("session") or {}
        n = sess_cfg.get("expire_after_booking_count")
        if n and self.bookings_completed >= n:
            self.invalidate_session()

    # ---- snapshots --------------------------------------------------------

    def snapshot(self) -> dict:
        with _lock:
            return {
                "scenario": self.scenario_name,
                "availability": copy.deepcopy(self.availability),
                "bookings": copy.deepcopy(self.bookings),
                "session_invalidated": self.session_invalidated,
                "cart_post_count": self.cart_post_count,
                "bookings_completed": self.bookings_completed,
            }


STATE = SimulatorState()
