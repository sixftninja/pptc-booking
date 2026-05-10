# PPTC Simulator

A locally running Flask app that mimics the PPTC member portal exactly
enough that the booker (`/Users/anand/Desktop/pptc-booking/book_courts.py`)
can be run against it without touching the real site.

The simulator hardcodes payment to always succeed (returns `TEST-XXXXXX`
confirmation numbers). Everything else — login flow, calendar HTML,
booking modal, cart, reCAPTCHA, My Reservations — is real-shaped so
Playwright selectors, race conditions, CAPTCHA handling, and session
recovery all get exercised.

## Setup

### Step 1: reCAPTCHA keys for localhost

Scenarios **3, 15, 16, 17** require real reCAPTCHA keys (the others use
Google's public test keys, which always pass). Five-minute setup:

1. Go to https://www.google.com/recaptcha/admin
2. Click `+` to create a new site
3. Label: `pptc-simulator`
4. Type: **reCAPTCHA v2** → "I'm not a robot" Checkbox
5. Domains: add `localhost`
6. Submit, copy Site Key and Secret Key
7. Paste into `simulator/.env` as `RECAPTCHA_SITE_KEY` and `RECAPTCHA_SECRET_KEY`

### Step 2: install dependencies

The simulator reuses the booker's Python environment.

```bash
conda activate pptc-booking
pip install -r requirements.txt
```

### Step 3: start the simulator

```bash
cd /Users/anand/Desktop/pptc-booking/simulator
FLASK_ENV=testing python app.py
```

The simulator runs at http://localhost:5000.

### Step 4: point the booker at the simulator

The runner sets these env vars automatically per subprocess. For ad-hoc
manual testing, set them in `/Users/anand/Desktop/pptc-booking/.env`:

```
MOCK_URL=http://localhost:5000/Member
CAPSOLVER_MOCK_URL=http://localhost:5000/capsolver-mock
TEST_MODE=1
```

`TEST_MODE=1` suppresses real SMTP and real git push — the booker writes
metadata to `simulator/test_results/booker_run_*.json` instead, which the
runner reads back.

### Step 5: run all 24 scenarios

```bash
# Terminal 1 — start the simulator (keep running)
cd /Users/anand/Desktop/pptc-booking/simulator
FLASK_ENV=testing python app.py

# Terminal 2 — run the full stress test
conda activate pptc-booking
cd /Users/anand/Desktop/pptc-booking/simulator
python runner.py
```

The full pass takes roughly 10–15 minutes. The runner prints a consolidated
report at the end and writes `test_results/full_run_*.json`.

### Step 6: run a single scenario manually

```bash
# Set scenario via admin endpoint
curl -X POST http://localhost:5000/admin/set-scenario \
  -H "Content-Type: application/json" \
  -d '{"scenario": "05_priority_fallback_all_hard_unavailable"}'

# Reset state
curl -X POST http://localhost:5000/admin/reset

# Run the booker
conda activate pptc-booking
cd /Users/anand/Desktop/pptc-booking
TEST_MODE=1 MOCK_URL=http://localhost:5000/Member \
  CAPSOLVER_MOCK_URL=http://localhost:5000/capsolver-mock \
  python book_courts.py
```

## Scenarios

| #  | Name                                          | Notes                                |
|----|-----------------------------------------------|--------------------------------------|
| 01 | Full availability, checkbox passes            | Test keys, baseline happy path       |
| 02 | Full availability, no CAPTCHA                 | Pure speed baseline                  |
| 03 | Full availability, forced CAPTCHA             | **Real keys required**               |
| 04 | Hard 9–10 unavailable                         | Expects priority 5                   |
| 05 | All hard unavailable                          | Expects priority 7                   |
| 06 | Hard empty, clay 13–16 only                   | Expects priority 19                  |
| 07 | Single hours only                             | Expects success_1h, priority 31      |
| 08 | Only 6b available                             | Expects no_slots                     |
| 09 | No slots at all                               | Expects no_slots                     |
| 10 | Race: hour 2 taken after hour 1               | Expects success_1h, partial email    |
| 11 | Race: TOCTOU on first slot                    | Expects priority 2 success           |
| 12 | Race: priorities 1–2 lost mid-flow            | Expects priority 3 success           |
| 13 | CAPTCHA at login only                         |                                      |
| 14 | CAPTCHA at booking only                       |                                      |
| 15 | CapSolver times out at login                  | **Real keys required**               |
| 16 | CapSolver times out at booking                | **Real keys required**               |
| 17 | CapSolver invalid key                         | **Real keys required**               |
| 18 | Slow calendar load (6s)                       | Tests Playwright timeout handling    |
| 19 | Slow type dropdown switch (4s)                |                                      |
| 20 | Cart hangs once then succeeds                 | Tests retry behavior                 |
| 21 | Confirmation never loads                      | Expects error_abort                  |
| 22 | Session expires immediately after login       | Tests re-login                       |
| 23 | Session expires between hour 1 and hour 2     | Tests re-login                       |
| 24 | My Reservations missing the booking           | Verification warning, dashboard OK   |

## Admin endpoints

Only respond when `FLASK_ENV=testing` and the request is from localhost.

```
POST /admin/set-scenario   {"scenario": "01_full_availability_checkbox"}
POST /admin/reset
GET  /admin/status
POST /admin/finish          (flush per-run instrumentation to disk)
```

## CapSolver mock

```
POST /capsolver-mock/createTask
POST /capsolver-mock/getTaskResult
```

Behavior follows the active scenario's `fault_injection` flags:
`capsolver_invalid_key` → 401, `capsolver_timeout` → always returns
`status: processing` so the booker hits its 60-second budget.

## Output files

- `test_results/scenario_NN_<name>_<TS>.json` — per-run server-side
  instrumentation (timings, events, bookings, errors)
- `test_results/booker_run_<TS>_<pid>.json` — per-run booker-side
  instrumentation (priority_hit, final_result, emails_sent, dashboard_updated)
- `test_results/full_run_<TS>.json` — runner-merged consolidated report
