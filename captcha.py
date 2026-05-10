"""CapSolver integration for solving Google reCAPTCHA v2 image challenges.

Uses a thin HTTP client (not the capsolver SDK) so the endpoint can be
overridden via CAPSOLVER_MOCK_URL when running against the simulator.

Flow:
  1. Detect the reCAPTCHA iframe on the cart page.
  2. Click the "I'm not a robot" checkbox.
  3. Wait briefly. If no image challenge appeared, we're done.
  4. If a challenge appeared, ask CapSolver to produce a g-recaptcha-response
     token, then inject it into the page DOM.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

import config

log = logging.getLogger(__name__)


class CaptchaError(Exception):
    """Raised when CAPTCHA cannot be solved within the budgeted time."""


def _api_key() -> str:
    api_key = os.getenv("CAPSOLVER_API_KEY", "").strip()
    if not api_key:
        raise CaptchaError("CAPSOLVER_API_KEY not set in environment")
    return api_key


def _capsolver_create_task(payload: dict) -> str:
    url = f"{config.CAPSOLVER_API_URL}/createTask"
    r = requests.post(url, json=payload, timeout=15)
    if r.status_code in (401, 403):
        raise CaptchaError(f"CapSolver auth rejected ({r.status_code}): {r.text[:200]}")
    if r.status_code >= 400:
        raise CaptchaError(f"CapSolver createTask HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    if body.get("errorId"):
        raise CaptchaError(f"CapSolver createTask error: {body}")
    task_id = body.get("taskId")
    if not task_id:
        raise CaptchaError(f"CapSolver createTask returned no taskId: {body!r}")
    return task_id


def _capsolver_get_result(task_id: str, deadline: float) -> dict:
    url = f"{config.CAPSOLVER_API_URL}/getTaskResult"
    while time.time() < deadline:
        r = requests.post(
            url,
            json={"clientKey": _api_key(), "taskId": task_id},
            timeout=15,
        )
        if r.status_code in (401, 403):
            raise CaptchaError(f"CapSolver auth rejected ({r.status_code}): {r.text[:200]}")
        if r.status_code >= 400:
            raise CaptchaError(f"CapSolver getTaskResult HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        if body.get("errorId"):
            raise CaptchaError(f"CapSolver getTaskResult error: {body}")
        status = body.get("status")
        if status == "ready":
            return body.get("solution") or {}
        if status not in ("processing", "idle"):
            raise CaptchaError(f"Unexpected CapSolver status: {body!r}")
        time.sleep(2)
    raise CaptchaError("CapSolver exceeded timeout budget")


def _solve_via_capsolver(sitekey: str) -> str:
    """Submit a CapSolver task and return the g-recaptcha-response token."""
    log.info("Submitting reCAPTCHA to CapSolver (sitekey=%s, endpoint=%s)",
             sitekey[:10] + "…", config.CAPSOLVER_API_URL)
    deadline = time.time() + config.CAPTCHA_TIMEOUT_S
    task_id = _capsolver_create_task({
        "clientKey": _api_key(),
        "task": {
            "type": "ReCaptchaV2TaskProxyless",
            "websiteURL": config.SITE_BASE_URL,
            "websiteKey": sitekey,
        },
    })
    solution = _capsolver_get_result(task_id, deadline)
    token = solution.get("gRecaptchaResponse")
    if not token:
        raise CaptchaError(f"CapSolver returned no token: {solution!r}")
    log.info("CapSolver returned token (%d chars)", len(token))
    return token


def _get_sitekey_from_iframe(page) -> Optional[str]:
    """Extract the data-sitekey attribute from the reCAPTCHA iframe."""
    try:
        sitekey = page.evaluate(
            """
            () => {
              const div = document.querySelector('.g-recaptcha[data-sitekey]');
              if (div) return div.getAttribute('data-sitekey');
              const iframe = document.querySelector('iframe[src*="recaptcha"]');
              if (iframe) {
                const m = iframe.src.match(/[?&]k=([^&]+)/);
                if (m) return decodeURIComponent(m[1]);
              }
              return null;
            }
            """
        )
        return sitekey
    except Exception as exc:
        log.warning("Could not extract sitekey: %s", exc)
        return None


def _click_checkbox(page) -> None:
    """Click the 'I'm not a robot' checkbox inside the reCAPTCHA iframe."""
    iframe_el = page.wait_for_selector(
        config.SELECTORS["recaptcha_iframe"], timeout=config.DEFAULT_TIMEOUT_MS
    )
    frame = iframe_el.content_frame()
    if frame is None:
        raise CaptchaError("reCAPTCHA iframe has no content frame")
    frame.wait_for_selector(
        config.SELECTORS["recaptcha_anchor_checkbox"],
        timeout=config.DEFAULT_TIMEOUT_MS,
    ).click()


def _challenge_visible(page) -> bool:
    """Detect whether an image challenge popup appeared after the checkbox click."""
    try:
        challenge = page.query_selector(config.SELECTORS["recaptcha_challenge_iframe"])
        if challenge is None:
            return False
        box = challenge.bounding_box()
        return bool(box and box.get("height", 0) > 0)
    except Exception:
        return False


def _inject_token(page, token: str) -> None:
    """Inject the solved token into both the textarea and any callback field."""
    page.evaluate(
        """
        (token) => {
          const ta = document.getElementById('g-recaptcha-response');
          if (ta) {
            ta.style.display = '';
            ta.value = token;
            ta.innerHTML = token;
          }
          document.querySelectorAll('textarea[name="g-recaptcha-response"]').forEach(el => {
            el.value = token;
            el.innerHTML = token;
          });
        }
        """,
        token,
    )


def solve_recaptcha(page) -> bool:
    """Solve the reCAPTCHA v2 on `page`. Returns True on success.

    Raises CaptchaError on unrecoverable failure.
    """
    log.info("Clicking reCAPTCHA checkbox")
    _click_checkbox(page)
    time.sleep(config.RECAPTCHA_CHECKBOX_WAIT_S)

    if not _challenge_visible(page):
        log.info("No image challenge appeared — checkbox was sufficient")
        return True

    log.info("Image challenge detected — handing off to CapSolver")
    sitekey = _get_sitekey_from_iframe(page)
    if not sitekey:
        raise CaptchaError("Could not extract reCAPTCHA sitekey from page")

    token = _solve_via_capsolver(sitekey)
    _inject_token(page, token)
    log.info("Token injected into g-recaptcha-response")
    return True
