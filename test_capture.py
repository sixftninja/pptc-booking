"""TEST_MODE side-effect capture.

When `config.TEST_MODE` is on, notifier and dashboard funnel their
side-effects through here instead of sending real email or pushing to git.
The runner reads the resulting JSON file to populate the
`emails_sent` / `dashboard_updated` fields of the consolidated report.

One file per booker process, identified by start timestamp + PID:
    simulator/test_results/booker_run_<YYYYMMDDHHMMSS>_<pid>.json
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_RUN_FILE: Path | None = None


def _run_file() -> Path:
    global _RUN_FILE
    if _RUN_FILE is None:
        config.TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        _RUN_FILE = config.TEST_OUTPUT_DIR / f"booker_run_{ts}_{os.getpid()}.json"
        # Initialize file with empty payload so a partial crash still leaves it
        # readable.
        _write({
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "scenario": os.getenv("ACTIVE_SCENARIO", ""),
            "emails_sent": [],
            "dashboard_updated": False,
            "dashboard_records": [],
            "priority_hit": None,
            "final_result": None,
            "errors": [],
        })
    return _RUN_FILE


def _read() -> dict:
    p = _run_file()
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write(data: dict) -> None:
    p = _run_file() if _RUN_FILE else config.TEST_OUTPUT_DIR / f"booker_run_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.getpid()}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, default=str))


def record_email(email_type: str, subject: str, body: str) -> None:
    if not config.TEST_MODE:
        return
    data = _read()
    data.setdefault("emails_sent", []).append({
        "type": email_type,
        "subject": subject,
        "body": body,
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    _write(data)
    log.info("[TEST_MODE] captured email: %s — %s", email_type, subject)


def record_dashboard(record: dict) -> None:
    if not config.TEST_MODE:
        return
    data = _read()
    data["dashboard_updated"] = True
    data.setdefault("dashboard_records", []).append({
        **record,
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    _write(data)
    log.info("[TEST_MODE] captured dashboard update")


def record_outcome(priority_hit: int | None, final_result: str) -> None:
    """Final summary the runner needs."""
    if not config.TEST_MODE:
        return
    data = _read()
    data["priority_hit"] = priority_hit
    data["final_result"] = final_result
    data["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _write(data)


def record_error(message: str) -> None:
    if not config.TEST_MODE:
        return
    data = _read()
    data.setdefault("errors", []).append({
        "msg": message,
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    _write(data)


def current_run_path() -> Path | None:
    return _RUN_FILE
