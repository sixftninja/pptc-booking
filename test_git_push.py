"""Verify git push to gh-pages works by writing a timestamp file, pushing,
then immediately pushing a cleanup commit that restores the previous state.

Run once before the first real booking:
    python test_git_push.py

Requires that git is configured (see README Step 4) and that the gh-pages
branch already exists (see README Step 6).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
HTML = "index.html"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(REPO), *args]
    print("$ " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout:
        print(r.stdout, end="")
    if r.stderr:
        print(r.stderr, end="")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (rc={r.returncode})")
    return r


def main() -> int:
    branch_before = run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    stashed = False
    if run("status", "--porcelain").stdout.strip():
        run("stash", "push", "-u", "-m", "test_git_push auto-stash")
        stashed = True

    try:
        run("fetch", "origin", "gh-pages", check=False)
        run("checkout", "gh-pages")
        run("pull", "--rebase", "origin", "gh-pages", check=False)

        prior = (REPO / HTML).read_text() if (REPO / HTML).exists() else None

        ts = datetime.now().isoformat(timespec="seconds")
        marker = f"<!doctype html><meta charset=utf-8><title>test</title><body>test push @ {ts}</body>"
        (REPO / HTML).write_text(marker)

        run("add", HTML)
        if not run("status", "--porcelain").stdout.strip():
            print("FAIL: marker file was identical to existing index.html (unlikely)", file=sys.stderr)
            return 1
        run("commit", "-m", f"test push: {ts}")
        run("push", "origin", "gh-pages")

        # Restore previous state.
        if prior is None:
            (REPO / HTML).unlink(missing_ok=True)
            run("rm", HTML)
        else:
            (REPO / HTML).write_text(prior)
            run("add", HTML)
        run("commit", "-m", f"test push cleanup: {ts}")
        run("push", "origin", "gh-pages")

        print("OK: test push + cleanup completed on gh-pages.")
        return 0

    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    finally:
        try:
            run("checkout", branch_before)
        except Exception:
            pass
        if stashed:
            try:
                run("stash", "pop")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
