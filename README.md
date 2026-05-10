# PPTC Booking

Books courts at the Prospect Park Tennis Center (PPTC) member portal at 6am
every Saturday and Sunday for the same day next week, and publishes a small
public dashboard of what got booked.

**Active range:** May 10, 2026 through September 27, 2026 (the last run books
October 4, the final day of outdoor season). The script exits immediately
with a log message if invoked outside this range.

---

## DIY

Want this for yourself? Don't fork — **regenerate it from scratch**. The
entire codebase, including this README, is produced from a single prompt
in [`DIY.md`](DIY.md). Open that file in [Claude Code](https://claude.com/claude-code),
paste it in, and let the agent build everything in a fresh folder.

A few warnings before you do:

- **Output varies by model and provider.** The same prompt against a
  different model — or the same model on a different day — will produce
  slightly different code. Selectors, error handling, and even file
  organization can shift. Read what the agent generates before running it.
- **Costs.** The build itself is one or two dollars in API calls.
  CapSolver charges per CAPTCHA solved (a few cents each). Gmail and
  GitHub Pages are free.
- **Bring your own keys.** You'll need: a member account on the PPTC
  Aptus portal, a Gmail App Password, a CapSolver API key, and a
  GitHub Personal Access Token with `repo` scope. The prompt explains
  where to get each.
- **Test before you trust.** The first time the script runs against the
  live site, it will almost certainly need selector tweaks (`config.py`).
  Watch the browser window before you let it loose on a real Saturday.
- **Pick your own paths and names.** Treat repo name, folder path,
  Anaconda location, and email address as parameters in the prompt — fill
  them in for your machine before you paste.

---

## Operational setup

### Step 1: Create conda environment

```bash
conda create -n pptc-booking python=3.11 -y
conda activate pptc-booking
```

### Step 2: Install dependencies

```bash
pip install playwright python-dotenv capsolver
playwright install chromium
```

### Step 3: Configure credentials

Copy `.env.example` to `.env` and fill in the blanks:

- `PPTC_EMAIL` — Aptus portal login email
- `PPTC_PASSWORD` — Aptus portal password
- `PPTC_ATTENDEE_NAME` — full name exactly as it appears in the booking modal's Attendee dropdown
- `NOTIFY_EMAIL` and `NOTIFY_EMAIL_FROM` — recipient and sender (can be the same address)
- `NOTIFY_EMAIL_PASSWORD` — Gmail App Password for the sender (16 characters, no spaces)
- `CAPSOLVER_API_KEY` — CapSolver API key

### Step 4: Configure GitHub credentials for automated git push

After every successful booking, the script pushes the dashboard update to
GitHub. To avoid password prompts, use a GitHub Personal Access Token:

1. github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token (classic), 1-year expiration, `repo` scope, copy it
3. Configure git to use it:

```bash
git config --global credential.helper store
git remote set-url origin https://YOUR_GITHUB_USERNAME:YOUR_PERSONAL_ACCESS_TOKEN@github.com/YOUR_GITHUB_USERNAME/pptc-booking.git
```

### Step 5: Initialize git and push to GitHub

```bash
cd ~/Desktop/pptc-booking
git init
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/pptc-booking.git
git add .
git status  # verify .env is NOT listed before continuing
git commit -m "Initial commit: PPTC court booking"
git branch -M main
git push -u origin main
```

### Step 6: Set up the GitHub Pages branch

```bash
git checkout --orphan gh-pages
git reset --hard
git commit --allow-empty -m "Init GitHub Pages"
git push origin gh-pages
git checkout main
```

In the GitHub repo: Settings → Pages → Source → `gh-pages` branch, `/` (root).
The dashboard will be live at `https://YOUR_GITHUB_USERNAME.github.io/pptc-booking`.

### Step 7: Schedule on macOS

Set the Mac to wake at 5:55am every day (the machine must be plugged in;
sleep is fine, shutdown is not):

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00
```

Also: System Settings → Battery → Options → enable
"Prevent automatic sleeping on power adapter when the display is off".

Add the cron job (`crontab -e`):

```
55 5 * * 6,0 ~/opt/anaconda3/envs/pptc-booking/bin/python ~/Desktop/pptc-booking/book_courts.py >> ~/Desktop/pptc-booking/logs/courts.log 2>&1
```

In cron, `6=Saturday`, `0=Sunday`. If Anaconda lives elsewhere, run
`conda activate pptc-booking && which python` to find the right path.

### Step 8: First manual test run

```bash
conda activate pptc-booking
cd ~/Desktop/pptc-booking
python book_courts.py
```

Watch the browser. Confirm login, calendar navigation, and the availability
scan look right before letting the cron job take over.

---

## How the priority list works

The script iterates through 44 ordered slot configurations and stops at the
first one it can fully (or partially) book.

| Steps | Goal                                                                |
|-------|----------------------------------------------------------------------|
| 1–6   | 9–11 / 10–12 / 11–13 on **hard** courts, same court then different   |
| 7–12  | Same windows on **clay** courts                                      |
| 13–28 | 12–14 / 13–15 / 14–16 / 15–17, alternating hard then clay            |
| 29–36 | Single 1-hour blocks on **hard**, 9 → 16                             |
| 37–44 | Single 1-hour blocks on **clay**, 9 → 16                             |

**Excluded under all circumstances:** Court 6b.

If the whole list runs out unbooked, the script sends a "no slots available"
email with a full availability dump and skips the dashboard update.

---

## Email notifications

| Subject                                    | When                                          |
|--------------------------------------------|-----------------------------------------------|
| 🎾 Booked! [Day] [Date] [Time] [Court]     | Full 2-hour or 1-hour booking succeeded       |
| 🎾 Partially Booked — [Day] [Date]         | Hour 1 booked, hour 2 failed (CAPTCHA / taken) |
| 🎾 CAPTCHA — book manually NOW             | CapSolver failed before any hour was booked   |
| 🎾 No slots available — [Day] [Date]       | Priority list exhausted                       |
| 🎾 PPTC error — [Day] [Date]               | Top-level exception                           |

---

## Logs

Every run writes to both stdout (captured by cron into `logs/courts.log`)
and a per-day file at `logs/courts_YYYY-MM-DD.log`.

---

## Manual testing

The first dry run is May 10, 2026 (booking for May 17). Cancel any
successful test booking manually before the first real Saturday. The same
priority list applies for all test runs.

---

## Adjusting selectors

The selectors in `config.SELECTORS` are best-guess CSS selectors. Once you've
watched the browser run once and seen the actual HTML, the most likely
things to adjust are:

- the **type dropdown** (custom widget vs. native `<select>`)
- the **calendar cell selector** in `browser.py` (`_cell_selector`)
- the **calendar date label** (which strftime format the page uses)
- the **modal field selectors** (Attendee, Item Details, Waiver)

All of these can be tweaked in one place: `config.py`.
