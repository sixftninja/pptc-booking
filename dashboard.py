"""GitHub Pages dashboard generator.

Maintains bookings.json + index.html on the gh-pages branch. Each successful
booking triggers:
    main → checkout gh-pages → update files → commit → push → checkout main

The bookings.json schema is a flat list of records:
    [
      {"date": "2026-05-17", "day": "Sun", "type": "hard",
       "courts": ["5a"], "hours": [9, 10],
       "confirmations": ["123456", "123457"],
       "booked_at": "2026-05-10T06:01:23"},
      ...
    ]
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import config
import test_capture

log = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parent


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory and return the CompletedProcess."""
    cmd = ["git", "-C", str(REPO_DIR), *args]
    log.debug("git: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result


def _current_branch() -> str:
    return _run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def _data_path() -> Path:
    return REPO_DIR / config.DASHBOARD_DATA_FILE


def _html_path() -> Path:
    return REPO_DIR / config.DASHBOARD_HTML_FILE


def _read_bookings() -> list[dict]:
    p = _data_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        log.warning("Could not parse %s — starting fresh", p)
        return []


def _write_bookings(bookings: list[dict]) -> None:
    _data_path().write_text(json.dumps(bookings, indent=2) + "\n")


def _render_html(bookings: list[dict]) -> str:
    """Render the dashboard HTML from the bookings list."""
    # Group by date.
    by_date: dict[str, list[dict]] = {}
    for b in bookings:
        by_date.setdefault(b["date"], []).append(b)

    sorted_dates = sorted(by_date.keys())
    now = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
    green = config.PPTC_GREEN

    rows_html = []
    if not sorted_dates:
        rows_html.append(
            '<tr><td colspan="4" class="empty">No bookings yet — '
            f'we start booking for {config.DASHBOARD_SEASON_LABEL.split(" – ")[0]}.</td></tr>'
        )
    else:
        for d_iso in sorted_dates:
            entries = by_date[d_iso]
            d_obj = datetime.fromisoformat(d_iso).date()
            day_label = d_obj.strftime("%a")
            date_label = d_obj.strftime("%b %-d")

            # Each date can have one or more booking records (a 2-hour block
            # is one record; if both hours got recorded as separate calls it's
            # two records — render whatever's there).
            for entry in entries:
                t_label = "Hard" if entry["type"] == "hard" else "Clay"
                courts = ", ".join(c.upper() for c in entry["courts"])
                hours = entry["hours"]
                if len(hours) == 1:
                    h = hours[0]
                    times = f"{h:02d}:00–{h+1:02d}:00"
                else:
                    h_min = min(hours)
                    h_max = max(hours) + 1
                    times = f"{h_min:02d}:00–{h_max:02d}:00"
                rows_html.append(
                    "<tr>"
                    f"<td><strong>{date_label}</strong></td>"
                    f"<td>{day_label}</td>"
                    f"<td><span class='type type-{entry['type']}'>{t_label}</span> {courts}</td>"
                    f"<td>{times}</td>"
                    "</tr>"
                )

    rows_joined = "\n      ".join(rows_html)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{config.DASHBOARD_TITLE}</title>
  <style>
    :root {{ --green: {green}; --green-dark: #355a40; --bg: #f7f8f7; --card: #ffffff;
              --text: #1f2a23; --muted: #6a7a70; --border: #e2e8e4; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                                  Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg); color: var(--text); }}
    header {{ background: var(--green); color: white; padding: 28px 20px; }}
    header h1 {{ margin: 0; font-size: 22px; font-weight: 600; }}
    header p  {{ margin: 6px 0 0; opacity: 0.85; font-size: 14px; }}
    main {{ max-width: 760px; margin: 24px auto; padding: 0 16px; }}
    .card {{ background: var(--card); border: 1px solid var(--border);
             border-radius: 10px; overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 15px; }}
    th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ background: #f0f4f1; color: var(--green-dark); font-weight: 600; font-size: 13px;
          text-transform: uppercase; letter-spacing: 0.04em; }}
    tr:last-child td {{ border-bottom: none; }}
    td.empty {{ text-align: center; color: var(--muted); padding: 32px 12px; }}
    .type {{ display: inline-block; padding: 2px 8px; border-radius: 999px;
             font-size: 12px; font-weight: 600; margin-right: 6px; }}
    .type-hard {{ background: #e6f0e9; color: var(--green-dark); }}
    .type-clay {{ background: #f1e2d6; color: #7a4a2a; }}
    footer {{ max-width: 760px; margin: 16px auto 32px; padding: 0 16px;
              color: var(--muted); font-size: 13px; text-align: center; }}
    @media (max-width: 520px) {{
      th, td {{ padding: 10px 8px; font-size: 14px; }}
      header {{ padding: 22px 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{config.DASHBOARD_TITLE}</h1>
    <p>Season: {config.DASHBOARD_SEASON_LABEL}</p>
  </header>
  <main>
    <div class="card">
      <table>
        <thead>
          <tr><th>Date</th><th>Day</th><th>Court</th><th>Time</th></tr>
        </thead>
        <tbody>
      {rows_joined}
        </tbody>
      </table>
    </div>
  </main>
  <footer>
    Last updated {now} · <a href="https://github.com/sixftninja/pptc-booking"
    style="color: var(--green-dark);">github.com/sixftninja/pptc-booking</a>
  </footer>
</body>
</html>
"""


def update_dashboard(target_date: date, court_type: str, courts: list[str],
                     hours: list[int], confirmations: list[str]) -> None:
    """Add a booking and push the regenerated dashboard to gh-pages.

    In TEST_MODE, no git operations happen — the would-be record is captured
    locally for the test runner.

    Otherwise: git failures are logged and re-raised so the caller can decide
    whether to alert. We never leave the repo on the wrong branch.
    """
    if config.TEST_MODE:
        record = {
            "date": target_date.isoformat(),
            "day": target_date.strftime("%a"),
            "type": court_type,
            "courts": list(courts),
            "hours": list(hours),
            "confirmations": list(confirmations),
        }
        test_capture.record_dashboard(record)
        return

    branch_before = _current_branch()
    log.info("Dashboard update: switching from %s to %s", branch_before, config.GITHUB_PAGES_BRANCH)

    # Stash any uncommitted changes on main before switching branches.
    stashed = False
    status = _run_git("status", "--porcelain").stdout.strip()
    if status:
        log.warning("Uncommitted changes on %s — stashing before branch switch", branch_before)
        _run_git("stash", "push", "-u", "-m", "pptc-booking auto-stash")
        stashed = True

    try:
        _run_git("fetch", "origin", config.GITHUB_PAGES_BRANCH, check=False)
        _run_git("checkout", config.GITHUB_PAGES_BRANCH)
        _run_git("pull", "--rebase", "origin", config.GITHUB_PAGES_BRANCH, check=False)

        bookings = _read_bookings()
        record = {
            "date": target_date.isoformat(),
            "day": target_date.strftime("%a"),
            "type": court_type,
            "courts": list(courts),
            "hours": list(hours),
            "confirmations": list(confirmations),
            "booked_at": datetime.now().isoformat(timespec="seconds"),
        }
        bookings.append(record)
        _write_bookings(bookings)

        _html_path().write_text(_render_html(bookings))

        _run_git("add", config.DASHBOARD_DATA_FILE, config.DASHBOARD_HTML_FILE)
        # If nothing changed (e.g. duplicate run), avoid empty commit.
        if _run_git("status", "--porcelain").stdout.strip():
            day_str = target_date.strftime("%a %b %-d")
            courts_str = "+".join(c.upper() for c in courts)
            hours_str = (f"{min(hours):02d}:00-{max(hours)+1:02d}:00"
                         if hours else "")
            commit_msg = f"Booking update: {day_str} {courts_str} {hours_str}".strip()
            _run_git("commit", "-m", commit_msg)
            _run_git("push", "origin", config.GITHUB_PAGES_BRANCH)
            log.info("Pushed dashboard update: %s", commit_msg)
        else:
            log.info("No dashboard changes to commit")

    finally:
        # Always return to the original branch.
        try:
            _run_git("checkout", branch_before)
        except Exception:
            log.exception("Failed to return to branch %s", branch_before)
        if stashed:
            try:
                _run_git("stash", "pop")
            except Exception:
                log.exception("Failed to pop stash")
