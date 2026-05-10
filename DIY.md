# DIY build prompt

Paste everything below the `--- BEGIN PROMPT ---` line into Claude Code (or
another capable coding agent) to generate the entire `pptc-booking`
codebase from scratch — including a copy of this `DIY.md` file itself and
a `README.md` whose first section is the DIY explainer.

Before you paste, do a find-and-replace inside the prompt for the
placeholders that depend on your machine and account:

| Placeholder                | Replace with                                                |
|----------------------------|-------------------------------------------------------------|
| `<LOCAL_REPO_PATH>`        | absolute path to the repo folder, e.g. `~/Desktop/pptc-booking` |
| `<GITHUB_USERNAME>`        | your GitHub username (the repo will live at `<GITHUB_USERNAME>/pptc-booking`) |
| `<ANACONDA_PATH>`          | path to your Anaconda install, e.g. `~/opt/anaconda3`       |

The placeholders only appear in user-facing setup instructions inside the
generated README — none are baked into source code.

---

--- BEGIN PROMPT ---

You are building a court reservation system for the Prospect Park Tennis
Center (PPTC) in Brooklyn. The local repo lives at `<LOCAL_REPO_PATH>`
and the GitHub repo will be `https://github.com/<GITHUB_USERNAME>/pptc-booking`.

Build the complete codebase from scratch in `<LOCAL_REPO_PATH>`. The full
specification follows. Produce production-ready, well-organized code that
matches it exactly.

## Naming and tone

The word "bot" is a casual internal nickname for this project — never put
it in file names, identifier names, code comments, README prose,
dashboard text, GitHub repo URLs, or commit messages. The user-facing
project name is "PPTC Booking" or "PPTC court booking system." It is fine
for the script to refer to itself as a "booking run" or simply "the script."

## Overview

A Python script that runs at 6:00am every Saturday and Sunday, logs into
the PPTC member portal, and books courts for the same day next week. It
also maintains a GitHub Pages dashboard at
`https://<GITHUB_USERNAME>.github.io/pptc-booking` showing what was booked.

Active date range: May 10, 2026 through September 27, 2026. The last run
books October 4, the final day of outdoor season. The script must exit
immediately with a log message if invoked outside this range.

## Tech stack

- Python 3.11
- Playwright (sync API, Chromium, NON-HEADLESS — must run with a visible
  browser for reCAPTCHA reliability)
- CapSolver Python SDK for image CAPTCHA solving
- python-dotenv for credentials
- smtplib for Gmail SMTP email notifications (built-in)
- Git CLI (subprocess calls) for GitHub Pages dashboard updates
- conda environment named `pptc-booking`

## File layout

```
<LOCAL_REPO_PATH>/
├── .env                  # credentials, gitignored
├── .env.example          # template, committed
├── .gitignore
├── README.md             # see structure below
├── DIY.md                # a copy of this prompt for future regeneration
├── config.py             # constants, selectors, priority list
├── book_courts.py        # main entry point
├── browser.py            # Playwright interactions
├── captcha.py            # CapSolver integration
├── notifier.py           # Gmail email sender
├── dashboard.py          # GitHub Pages JSON + HTML + git pusher
└── logs/                 # created at runtime, gitignored
```

## Credentials (`.env`)

Create both `.env` and `.env.example` containing the same set of empty
keys. Do not pre-fill any email address or personal name. Each value is
left blank for the user to fill in.

Required keys:

```
PPTC_EMAIL=
PPTC_PASSWORD=
PPTC_ATTENDEE_NAME=
NOTIFY_EMAIL=
NOTIFY_EMAIL_FROM=
NOTIFY_EMAIL_PASSWORD=
CAPSOLVER_API_KEY=
```

`PPTC_ATTENDEE_NAME` is the user's full name as it appears in the
booking modal's Attendee dropdown. It must be configurable via the `.env`
file — never hardcoded.

## Site details

Login URL: `https://prospectpark.aptussoft.com/Member`
- Email field, Password field, Sign In button. No CAPTCHA at login.

After login, the left nav is always visible on desktop (no hamburger).
Nav structure: Programs & Services → Court Reservation.

Court Reservation page:
- Type dropdown at the top: options are "Hard" and "Clay".
- "Hard" shows: Court 5a, Court 4a (2 columns).
- "Clay" shows: Court 3a, Court 2a, Court 1a, Court 4b, Court 5b, Court 6b (6 columns).
- Calendar shows time rows from 6am to 10pm in 1-hour increments.
- Available slots are empty white cells (clickable).
- Reserved slots are greyed out with "RESERVED" text (not clickable).
- Navigation arrows move the calendar forward/backward by day.
- Target date = today + 7 days exactly.

Booking flow when clicking an empty cell:

1. A modal opens with: StartTime (pre-filled), EndTime (pre-filled),
   Attendee dropdown (select the value of `PPTC_ATTENDEE_NAME`), Item
   Details dropdown (select "Online Indoor Court"), Appt Notes textarea
   (leave empty), waiver checkbox, Go button, Cancel button.
2. Check the waiver checkbox (label begins with "I have read and understand").
3. Click Go.
4. Cart page loads showing: location, member name, class description,
   qty, price ($84), total, deposit/amount due, Continue Shopping and
   Clear Cart buttons.
5. Scroll down — payment section shows amount and credit card on file.
6. reCAPTCHA appears: "I'm not a robot" checkbox (Google reCAPTCHA v2).
7. After CAPTCHA passes, a confirmation message
   "The transaction has been approved. Your confirmation number is XXXXXX"
   appears both inline and as a popup dialog.
8. Click Ok on the popup.
9. Booking complete.

Confirmation verification:
After booking, navigate to Account Activity → My Reservations in the left
nav. The page shows reservations for a date range. Verify the booked court
appears with correct date, time, and court number before sending the
success notification. If verification fails, send a warning email but do
**not** retry the booking — that risks double-charging.

## Court configuration

- Hard courts (preferred): 4a, 5a (no order preference, both equally good)
- Clay courts (fallback): 3a, 2a, 1a, 4b, 5b
- ALWAYS EXCLUDED: 6b (never book this court under any circumstances)

## Priority list (44 steps, execute top to bottom, stop at first success)

2-hour blocks:

```
1.  09:00–11:00 hard, same court
2.  09:00–11:00 hard, different courts
3.  10:00–12:00 hard, same court
4.  10:00–12:00 hard, different courts
5.  11:00–13:00 hard, same court
6.  11:00–13:00 hard, different courts
7.  09:00–11:00 clay, same court
8.  09:00–11:00 clay, different courts
9.  10:00–12:00 clay, same court
10. 10:00–12:00 clay, different courts
11. 11:00–13:00 clay, same court
12. 11:00–13:00 clay, different courts
13. 12:00–14:00 hard, same court
14. 12:00–14:00 hard, different courts
15. 12:00–14:00 clay, same court
16. 12:00–14:00 clay, different courts
17. 13:00–15:00 hard, same court
18. 13:00–15:00 hard, different courts
19. 13:00–15:00 clay, same court
20. 13:00–15:00 clay, different courts
21. 14:00–16:00 hard, same court
22. 14:00–16:00 hard, different courts
23. 14:00–16:00 clay, same court
24. 14:00–16:00 clay, different courts
25. 15:00–17:00 hard, same court
26. 15:00–17:00 hard, different courts
27. 15:00–17:00 clay, same court
28. 15:00–17:00 clay, different courts
```

Single hours (hard first, then clay, earlier before later):

```
29. 09:00–10:00 hard
30. 10:00–11:00 hard
31. 11:00–12:00 hard
32. 12:00–13:00 hard
33. 13:00–14:00 hard
34. 14:00–15:00 hard
35. 15:00–16:00 hard
36. 16:00–17:00 hard
37. 09:00–10:00 clay
38. 10:00–11:00 clay
39. 11:00–12:00 clay
40. 12:00–13:00 clay
41. 13:00–14:00 clay
42. 14:00–15:00 clay
43. 15:00–16:00 clay
44. 16:00–17:00 clay
```

If all 44 steps fail: send an alert email with a full availability dump
and skip the dashboard update.

## CAPTCHA handling

Step 1: Run the browser non-headless with a realistic Mac user-agent:
`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36`.

Step 2: On the cart page, find the reCAPTCHA iframe and click the
"I'm not a robot" checkbox. Wait 3 seconds. Check whether an image
challenge appeared.

Step 3: If an image challenge appeared, use CapSolver:
- Use the `capsolver` Python SDK
- Task type: `ReCaptchaV2TaskProxyless`
- Get the sitekey from the reCAPTCHA iframe (the `data-sitekey` attribute
  on the surrounding `.g-recaptcha` div, or the `k=` query param of the
  iframe `src`)
- Site URL: `https://prospectpark.aptussoft.com`
- Submit task, poll for solution, inject the `g-recaptcha-response` token
- Timeout: 60 seconds maximum

Step 4: If CapSolver fails or times out, send an email alert with slot
details and exit.

Edge case — hour 1 books, CAPTCHA fails on hour 2:
Send email "Booked [court] [time1]. Could not book [time2] — CAPTCHA failed.
Book manually." Do not attempt any further slots. Update the dashboard
with the 1 hour that was booked.

Edge case — hour 1 books, hour 2 slot taken by someone else in the meantime:
Send email "Booked [court] [time1] only. [time2] was taken before we could
book it." Do not book a replacement. Update the dashboard with the 1 hour
that was booked.

## Email notifications

Sender: read from `NOTIFY_EMAIL_FROM` (Gmail App Password auth via
`smtplib.SMTP_SSL` on port 465).
Recipient: read from `NOTIFY_EMAIL`.

Email types:

1. **Success (full 2 hours)** — Subject: `🎾 Booked! [Day] [Date] [Time] [Court]`. Body: all booking details, both confirmation numbers.
2. **Success (1 hour only, partial)** — Subject: `🎾 Partially Booked — [Day] [Date]`. Body: what was booked, what wasn't, why.
3. **CAPTCHA alert** — Subject: `🎾 CAPTCHA — book manually NOW`. Body: exact slot to grab, login URL, note that CapSolver was attempted.
4. **No slots** — Subject: `🎾 No slots available — [Day] [Date]`. Body: full availability dump.
5. **Error** — Subject: `🎾 PPTC error — [Day] [Date]`. Body: exception details and context.

## GitHub Pages dashboard

Branch: `gh-pages`
File: `index.html` at the root of the `gh-pages` branch
Data file: `bookings.json` alongside `index.html` to persist the season's record

After every successful booking (full or partial):

1. Stash any uncommitted work on the current branch.
2. Check out `gh-pages`.
3. Pull (rebase) latest from origin.
4. Read `bookings.json` (or treat as empty if missing).
5. Append the new booking record.
6. Regenerate `index.html` from the data.
7. Commit with a clear message such as `Booking update: [Day] [Date] [Court] [Time]`.
8. Push to `origin gh-pages`.
9. Switch back to the original branch and pop the stash.

The dashboard HTML must be:
- Clean, mobile-friendly, single page
- Show the current outdoor season's bookings (May 17 – Oct 4, 2026)
- Group by date; columns: Date, Day, Court type (Hard/Clay), Court number(s), Time(s)
- Show "No bookings yet" if empty
- Show a last-updated timestamp
- PPTC green color scheme (`#4a7c59`)
- No login required, fully public

## Setup instructions in the README

The generated `README.md` has these sections, in order:

1. **Title and one-paragraph description** ("PPTC Booking" — no "bot").
2. **DIY** (this is the FIRST section after the title). It says: "want
   this for yourself? Don't fork — regenerate from scratch." It links to
   `DIY.md`. It includes warnings about:
   - Output varies by model and provider; read what gets generated
   - Costs (API call cost for the build, CapSolver per-CAPTCHA costs)
   - Bring your own keys (Aptus account, Gmail App Password, CapSolver,
     GitHub Personal Access Token)
   - First-run selectors will likely need tweaking — watch the browser
   - Use placeholders for paths/usernames specific to your machine
3. **Operational setup** — eight steps:
   - Step 1: `conda create -n pptc-booking python=3.11 -y` and activate
   - Step 2: `pip install playwright python-dotenv capsolver` then `playwright install chromium`
   - Step 3: copy `.env.example` → `.env` and fill in the blanks (with a
     bullet-list explanation for each variable)
   - Step 4: GitHub Personal Access Token instructions and `git config`
     plus `git remote set-url` (with `<GITHUB_USERNAME>` placeholders)
   - Step 5: `git init`, add remote, first commit and push to `main`
   - Step 6: orphan `gh-pages` branch + Pages settings + dashboard URL
   - Step 7: macOS scheduling — `sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00`,
     System Settings → Battery → "Prevent automatic sleeping…", and the
     crontab line:
     ```
     55 5 * * 6,0 <ANACONDA_PATH>/envs/pptc-booking/bin/python <LOCAL_REPO_PATH>/book_courts.py >> <LOCAL_REPO_PATH>/logs/courts.log 2>&1
     ```
     (cron `6=Saturday`, `0=Sunday`)
   - Step 8: first manual test run with a note to watch the browser
4. **How the priority list works** — short table summary
5. **Email notifications** — table of subject lines and triggers
6. **Logs** — note about stdout + dated per-run file in `logs/`
7. **Manual testing** — first dry run is May 10, 2026 (booking for May 17)
8. **Adjusting selectors** — list of likely-to-change selectors, all
   tweakable in `config.py`

Do **not** include a separate "Architecture at a glance" section.

## DIY.md content

Generate a `DIY.md` file that contains:

1. A short intro explaining what the file is and how to use it.
2. The placeholder table (`<LOCAL_REPO_PATH>`, `<GITHUB_USERNAME>`,
   `<ANACONDA_PATH>`).
3. The full prompt itself, framed by `--- BEGIN PROMPT ---` and
   `--- END PROMPT ---` markers, so it can be copy-pasted into the next
   regeneration.

The prompt body inside `DIY.md` must be a faithful reproduction of this
specification (so future regenerations stay consistent). Anyone reading
`DIY.md` can paste the inner prompt back into Claude Code and rebuild the
whole project.

## Logging

Use the Python `logging` module. Every run logs to both stdout and
`logs/courts_YYYY-MM-DD.log` (date of the run). Default level INFO. Log
every meaningful step: login, calendar navigation, availability scan,
each booking attempt, CAPTCHA outcome, confirmation check, email sent,
dashboard update.

## Error handling principles

- Never let an unhandled exception silently kill the run — always catch at
  the top level and send the error email
- Session timeout: if detected mid-run, re-login once and retry the
  current step
- If the My Reservations confirmation check fails to find the booking,
  send a warning email but do **not** book again
- All Playwright waits use explicit `wait_for_selector` with reasonable
  timeouts (10–15 seconds), never `time.sleep` except briefly after clicks
  (0.5 seconds max)

## Testing notes

First test run: May 10, 2026 (booking for May 17). Same priority list
applies for all test runs. After a successful test booking, cancel
manually before the first real Saturday. Watch the browser window during
test runs to confirm navigation is correct.

## Final deliverables

After creating all files, show:

1. The complete list of files created.
2. Confirmation that all setup steps appear in `README.md` exactly as
   specified above.
3. Any assumptions made or things likely to need adjustment after the
   first test run (especially selectors).

--- END PROMPT ---
