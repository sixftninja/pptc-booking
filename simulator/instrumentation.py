"""Per-run instrumentation captured server-side.

Each scenario run produces one JSON file:
    test_results/scenario_NN_<scenario-name>_<TS>.json

The runner merges this with the booker's own JSON (booker_run_<TS>.json) to
produce the final consolidated report.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "test_results"

_lock = threading.Lock()


class RunInstrumentation:
    """One instance lives for the duration of a single bot run against the sim."""

    def __init__(self) -> None:
        self.scenario_name: str = ""
        self.scenario_number: int = 0
        self.run_start: float | None = None
        self.run_end: float | None = None
        self.events: list[dict] = []  # generic event log
        self.timings: dict[str, float] = {}  # named durations in seconds
        self.bookings: list[dict] = []
        self.errors: list[str] = []

    # ---- lifecycle ---------------------------------------------------------

    def start(self, scenario_name: str, scenario_number: int) -> None:
        with _lock:
            self.scenario_name = scenario_name
            self.scenario_number = scenario_number
            self.run_start = time.time()
            self.run_end = None
            self.events = []
            self.timings = {}
            self.bookings = []
            self.errors = []

    def stop(self) -> None:
        with _lock:
            self.run_end = time.time()

    # ---- events ------------------------------------------------------------

    def record_event(self, name: str, **fields: Any) -> None:
        with _lock:
            self.events.append({
                "name": name,
                "at": time.time(),
                **fields,
            })

    def record_timing(self, key: str, seconds: float) -> None:
        with _lock:
            self.timings[key] = seconds

    def record_booking(self, **fields: Any) -> None:
        with _lock:
            self.bookings.append({"at": time.time(), **fields})

    def record_error(self, msg: str) -> None:
        with _lock:
            self.errors.append(msg)

    # ---- output ------------------------------------------------------------

    def to_dict(self) -> dict:
        with _lock:
            duration = (self.run_end - self.run_start) if (self.run_end and self.run_start) else None
            return {
                "scenario_name": self.scenario_name,
                "scenario_number": self.scenario_number,
                "run_start": self.run_start,
                "run_end": self.run_end,
                "total_duration_seconds": duration,
                "timings": dict(self.timings),
                "bookings": list(self.bookings),
                "events": list(self.events),
                "errors": list(self.errors),
            }

    def write(self) -> Path:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sn = self.scenario_number or 0
        path = RESULTS_DIR / f"scenario_{sn:02d}_{self.scenario_name}_{ts}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        return path


# Module-level singleton — Flask is single-process; we run scenarios serially.
INSTR = RunInstrumentation()


# ---- timing helpers --------------------------------------------------------


class TimedBlock:
    """Context manager that records elapsed wall time under a key."""

    def __init__(self, key: str):
        self.key = key
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        INSTR.record_timing(self.key, time.time() - self._start)
        return False
