"""CAPTCHA mode handler for the simulator.

Modes (per scenario / .env):
    none     — render no widget at all
    test     — render Google's public test keys; checkbox always passes
    natural  — real keys; Google decides based on browser risk signals
    forced   — real keys; server forces image challenge by ignoring the
               checkbox response (or by the booker hitting a sitekey it
               can't solve when capsolver_timeout is on)

The simulator only chooses *which sitekey* to render and *whether to require
a g-recaptcha-response token on submit*. It does not itself verify tokens
against Google for this project — token presence is sufficient to proceed
to the simulated payment success.
"""

from __future__ import annotations

import os


def sitekey_for_mode(mode: str) -> str:
    if mode == "none":
        return ""
    if mode == "test":
        return os.getenv("RECAPTCHA_TEST_SITE_KEY", "")
    # natural / forced
    return os.getenv("RECAPTCHA_SITE_KEY", "") or os.getenv("RECAPTCHA_TEST_SITE_KEY", "")


def widget_required(mode: str) -> bool:
    return mode in ("test", "natural", "forced")


def token_required(mode: str) -> bool:
    """When True, the cart submit endpoint expects g-recaptcha-response."""
    return mode in ("test", "natural", "forced")
