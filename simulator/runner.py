"""Stress test runner — execute all 24 scenarios sequentially.

Run from a second terminal while `python app.py` is running in the first:

    cd /Users/anand/Desktop/pptc-booking/simulator
    python runner.py

For each scenario the runner:
  1. POSTs /admin/set-scenario  (loads JSON, resets state, restarts instrumentation)
  2. POSTs /admin/reset
  3. Subprocesses the booker with TEST_MODE=1, MOCK_URL pointed at the simulator,
     and CAPSOLVER_MOCK_URL pointed at the simulator's mock endpoint
  4. Waits up to 3 minutes for the booker to exit
  5. POSTs /admin/finish to flush server-side instrumentation
  6. Reads both the simulator instrumentation file and the booker's
     booker_run JSON, merges them
  7. Compares actual vs. expected_result / expected_priority_hit and records
     pass/fail

After all 24 finish, prints the consolidated report and writes
test_results/full_run_<timestamp>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCENARIOS_DIR = HERE / "scenarios"
RESULTS_DIR = HERE / "test_results"

SIM_BASE = os.getenv("SIM_BASE", "http://127.0.0.1:5000")
BOOKER = ROOT / "book_courts.py"
PER_SCENARIO_TIMEOUT = 180  # seconds


def _list_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def _api_post(path: str, body: dict | None = None) -> dict:
    r = requests.post(f"{SIM_BASE}{path}", json=body or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _api_get(path: str) -> dict:
    r = requests.get(f"{SIM_BASE}{path}", timeout=15)
    r.raise_for_status()
    return r.json()


def _wait_for_simulator() -> bool:
    for _ in range(60):
        try:
            r = requests.get(f"{SIM_BASE}/admin/status", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _read_scenario(name: str) -> dict:
    return json.loads((SCENARIOS_DIR / f"{name}.json").read_text())


def _newest_file(prefix: str) -> Optional[Path]:
    candidates = sorted(RESULTS_DIR.glob(f"{prefix}*.json"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _run_scenario(name: str) -> dict:
    """Run a single scenario, return merged result dict."""
    scenario = _read_scenario(name)
    expected_result = scenario.get("expected_result")
    expected_priority = scenario.get("expected_priority_hit")

    print(f"\n>> [{name}] setting scenario", flush=True)
    _api_post("/admin/set-scenario", {"scenario": name})
    _api_post("/admin/reset")

    env = os.environ.copy()
    env["TEST_MODE"] = "1"
    env["MOCK_URL"] = f"{SIM_BASE}/Member"
    env["CAPSOLVER_MOCK_URL"] = f"{SIM_BASE}/capsolver-mock"
    env["ACTIVE_SCENARIO"] = name
    # Make sure the booker can find a CapSolver "API key" — anything non-empty works
    # because our mock doesn't validate it (except in capsolver_invalid_key scenarios).
    env.setdefault("CAPSOLVER_API_KEY", "test-key")
    env.setdefault("PPTC_EMAIL", "test@example.com")
    env.setdefault("PPTC_PASSWORD", "testpass")
    env.setdefault("PPTC_ATTENDEE_NAME", "Anand Altekar")
    env.setdefault("NOTIFY_EMAIL", "test@example.com")
    env.setdefault("NOTIFY_EMAIL_FROM", "test@example.com")
    env.setdefault("NOTIFY_EMAIL_PASSWORD", "test-app-password")

    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(BOOKER)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=PER_SCENARIO_TIMEOUT,
        )
        timed_out = False
        rc = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        rc = -1
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    duration = time.time() - start

    # Flush sim instrumentation.
    try:
        _api_post("/admin/finish")
    except Exception:
        pass

    # Merge instrumentation.
    sim_file = _newest_file(f"scenario_{int(name.split('_', 1)[0]):02d}_") if name[:2].isdigit() else _newest_file("scenario_")
    booker_file = _newest_file("booker_run_")
    sim_data = json.loads(sim_file.read_text()) if sim_file else {}
    booker_data = json.loads(booker_file.read_text()) if booker_file else {}

    actual_result = booker_data.get("final_result")
    actual_priority = booker_data.get("priority_hit")

    passed = True
    reasons: list[str] = []
    if timed_out:
        passed = False
        reasons.append(f"booker timed out (>{PER_SCENARIO_TIMEOUT}s)")
    if expected_result and actual_result != expected_result:
        passed = False
        reasons.append(f"final_result {actual_result!r} != expected {expected_result!r}")
    if expected_priority is not None and actual_priority != expected_priority:
        passed = False
        reasons.append(f"priority_hit {actual_priority!r} != expected {expected_priority!r}")
    if rc not in (0,) and not timed_out and expected_result and "success" in expected_result:
        passed = False
        reasons.append(f"booker exited rc={rc}")

    return {
        "scenario": name,
        "scenario_number": int(name.split("_", 1)[0]) if name[:2].isdigit() else 0,
        "scenario_human": scenario.get("name"),
        "duration_seconds": duration,
        "expected_result": expected_result,
        "expected_priority_hit": expected_priority,
        "actual_result": actual_result,
        "actual_priority_hit": actual_priority,
        "passed": passed,
        "reasons": reasons,
        "timed_out": timed_out,
        "booker_rc": rc,
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
        "sim_instrumentation_file": str(sim_file) if sim_file else None,
        "booker_run_file": str(booker_file) if booker_file else None,
        "sim_timings": sim_data.get("timings", {}),
        "emails_sent": booker_data.get("emails_sent", []),
        "dashboard_updated": booker_data.get("dashboard_updated", False),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_time(seconds: float) -> str:
    return f"{seconds:5.1f}s"


def _print_report(results: list[dict], total_seconds: float) -> None:
    line = "═" * 68
    bar = "║"
    print(f"\n╔{line}╗")
    title = "PPTC SIMULATOR — FULL STRESS TEST REPORT"
    print(f"{bar} {title:^66} {bar}")
    print(f"{bar} Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {len(results)} scenarios{' ' * 30}{bar}"[:69+len(bar)*2])
    print(f"╠{line}╣")
    print(f"{bar}  #  {'Scenario':<36} {'Result':<8}{'Pri':<5}{'Time':<8}{bar}")
    print(f"╠{line}╣")
    passed = failed = 0
    cap_solves: list[float] = []
    fastest = None
    slowest = None
    for r in results:
        ok = "✅ PASS" if r["passed"] else "❌ FAIL"
        if r["passed"]:
            passed += 1
        else:
            failed += 1
        sn = r["scenario_number"]
        name_short = (r["scenario_human"] or r["scenario"])[:36]
        pri = f"P{r['actual_priority_hit']}" if r["actual_priority_hit"] is not None else "—"
        dur = _fmt_time(r["duration_seconds"])
        print(f"{bar} {sn:>2}  {name_short:<36} {ok:<8}{pri:<5}{dur:<8}{bar}")
        if "success" in (r["expected_result"] or ""):
            d = r["duration_seconds"]
            fastest = d if fastest is None else min(fastest, d)
            slowest = d if slowest is None else max(slowest, d)
        for evt in (r.get("sim_timings", {}) or {}):
            pass  # placeholder
    print(f"╠{line}╣")
    print(f"{bar}  PASSED: {passed}/{len(results)}   FAILED: {failed}/{len(results)}   TOTAL TIME: {total_seconds:.1f}s{' ' * (45 - len(str(passed)) - len(str(failed)))}{bar}")
    print(f"╠{line}╣")
    print(f"{bar}  TIMING SUMMARY{' ' * 51}{bar}")
    if fastest is not None:
        print(f"{bar}  Fastest end-to-end: {_fmt_time(fastest)}{' ' * 41}{bar}")
    if slowest is not None:
        print(f"{bar}  Slowest end-to-end: {_fmt_time(slowest)}{' ' * 41}{bar}")
    print(f"╚{line}╝")
    if failed:
        print("\nFailures:")
        for r in results:
            if not r["passed"]:
                print(f"  {r['scenario']}: {'; '.join(r['reasons']) or '(see logs)'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Run a single scenario by name (or number prefix)")
    parser.add_argument("--from", dest="start_from", help="Start from this scenario name")
    args = parser.parse_args()

    if not _wait_for_simulator():
        print(f"FAIL: simulator at {SIM_BASE} did not respond. "
              f"Start it with `FLASK_ENV=testing python app.py` first.",
              file=sys.stderr)
        return 1

    scenarios = _list_scenarios()
    if args.only:
        scenarios = [s for s in scenarios if s == args.only or s.startswith(args.only + "_") or s.startswith(args.only)]
        if not scenarios:
            print(f"No scenario matches {args.only}", file=sys.stderr)
            return 1
    if args.start_from:
        try:
            idx = next(i for i, s in enumerate(scenarios) if s.startswith(args.start_from))
            scenarios = scenarios[idx:]
        except StopIteration:
            print(f"No scenario starts with {args.start_from}", file=sys.stderr)
            return 1

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    t0 = time.time()
    for s in scenarios:
        try:
            results.append(_run_scenario(s))
        except Exception as exc:
            print(f"ERROR running {s}: {exc}", file=sys.stderr)
            results.append({
                "scenario": s,
                "scenario_number": int(s.split("_", 1)[0]) if s[:2].isdigit() else 0,
                "scenario_human": s,
                "duration_seconds": 0,
                "expected_result": None,
                "expected_priority_hit": None,
                "actual_result": None,
                "actual_priority_hit": None,
                "passed": False,
                "reasons": [f"runner exception: {exc}"],
                "timed_out": False,
                "booker_rc": -1,
                "stdout_tail": "", "stderr_tail": "",
                "sim_instrumentation_file": None, "booker_run_file": None,
                "sim_timings": {}, "emails_sent": [], "dashboard_updated": False,
            })
    total = time.time() - t0

    _print_report(results, total)

    out_path = RESULTS_DIR / f"full_run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    out_path.write_text(json.dumps({
        "run_start": t0,
        "run_end": time.time(),
        "total_seconds": total,
        "results": results,
    }, indent=2, default=str))
    print(f"\nDetailed report: {out_path}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
