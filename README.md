# PPTC Booking

**Status: abandoned, 2026-05-15. Never booked a court.**

This was an attempt to build a Python bot that would log into the Prospect
Park Tennis Center member portal at 6am every Saturday and Sunday and
book courts for the same day next week, with email notifications and a
public dashboard. The code is here as a record of what we tried.

## What we built

A full pipeline: a Playwright-driven Chromium booker that walked a
44-step priority list of preferred slot/court combinations, with session
re-login, TOCTOU retries, partial-booking flows, and CapSolver integration
for the cart's reCAPTCHA. A Gmail SMTP notifier. A GitHub Pages dashboard
that re-rendered on every booking. A 25-scenario Flask simulator to test
all of it offline. Standalone smoke tests for email and git-push.

All of it works *in isolation* — login authenticates against the real
site, calendar navigation works, emails send, the dashboard updates,
the simulator passes 25 of 25 scenarios.

## Why it didn't work

The bot was written from a written spec describing what a user *sees* on
the booking calendar — a grid of green and red cells you click. The real
calendar uses FullCalendar.js's resource-day view: each court is one big
invisible column, and reserved slots are absolutely-positioned colored
rectangles overlaid at pixel offsets. **There are no per-cell DOM elements
at all.**

When the bot scanned for "cells marked available" it found none, and
concluded no slots were open — the exact opposite of the truth. Nearly
every slot looked open to it, because the scanner was looking for the
wrong shape of HTML entirely.

The simulator we built to test the bot baked in the same wrong
assumption, so all 25 scenarios passed while the bot couldn't book a
single real court.

## Lesson

Inspect the live DOM before writing any selector. A UX description of a
page is not a DOM description. A simulator built from the same
assumption as the bot proves nothing — it produces false confidence.

The full story, including the real FullCalendar selectors we eventually
discovered and what's salvageable from this codebase, is in
[POSTMORTEM.md](POSTMORTEM.md).
