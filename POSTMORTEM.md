# PPTC Booking Bot — Post-mortem

**Status:** Project abandoned 2026-05-15. Never used for a real booking.

## Goal

Auto-book PPTC tennis courts at 6am Sat/Sun for the same day next week, with
email notifications and a GitHub Pages dashboard.

## What worked end-to-end

- Gmail SMTP notifications — verified live (`test_email.py`)
- Git push to `gh-pages` branch — verified live (`test_git_push.py`)
- GitHub Pages dashboard — live at https://sixftninja.github.io/pptc-booking/
- Booker scaffolding: 44-entry priority list, date guard, `FORCE_RUN` override,
  session re-login mid-run, TOCTOU retry within priority entry, permit-court
  (4b/5b after 19:00) constraint, `TEST_MODE` plumbing
- CapSolver HTTP shim — API auth + balance check verified
- Live login against real PPTC site (after we discovered real selectors)
- Live calendar date navigation via FullCalendar's `gotoDate` JS API
- `#Resource` (Hard/Clay) dropdown switching
- Simulator with 25 scenarios — turned out to be the wrong model (see below)

## What didn't work

- The booker's **availability scanner**. The real PPTC calendar doesn't have
  per-cell DOM nodes. The bot scanned for cells matching
  `[data-court="X"][data-hour="HH:00"]`, found none, and concluded "no slots"
  — the opposite of reality.
- We **never tested** the booking modal, cart, reCAPTCHA, confirmation popup,
  or My Reservations against the real site — blocked by the scanner failure
  and an intermittent site-side JS 404.

## Root cause

The entire bot was built from a **written spec describing what a user sees**
on the calendar page (a grid of green/red cells you click). The **real DOM
is structured completely differently** — FullCalendar.js renders one big
`<td>` per court with reserved slots as absolutely-positioned overlay divs.
The spec was a UX description, not a DOM description. The code was built
against the description, not the reality.

Three downstream consequences:

1. Selectors were wrong throughout — calendar nav, type dropdown, cell
   selectors, modal selectors, cart selectors.
2. The simulator we built to "test" the bot baked in the same wrong
   assumptions, producing **false confidence**. All 25 scenarios passed in
   simulation; zero would have worked against the live site.
3. Every fix was reactive — each live run surfaced one more selector
   mismatch, with no end in sight.

## Key findings from live inspection

### Login (`/Member`)
- Email input: `#email` (lowercase id; type is `"text"`, not `"email"`)
- Password input: `#password`
- Submit button: `#btnSignIn`

### Court Reservation calendar (`/Member/Aptus/Calender`)
- Uses **FullCalendar.js** resource-day view
- Court type dropdown: `select#Resource` (options "Clay" / "Hard")
- Date label: `<h2>` inside `.fc-header-title`
- Date navigation: `$('#calendar').fullCalendar('gotoDate', new Date(iso))`
  — JS API, far more reliable than clicking the arrow `<span>`s
- Court columns identified by class `fc-resourceid-Clay2`, `fc-resourceid-Clay3`, etc.
- Column display labels in the `<th>` inner text: "Court 3a", "Court 2a", etc.

### Court ID ↔ display label mapping (Clay tab, observed)

| Internal id | Display label |
|---|---|
| `Clay2` | Court 3a |
| `Clay3` | Court 2a |
| `Clay4` | Court 1a |
| `Clay7` | Court 4b |
| `Clay8` | Court 5b |
| `Clay9` | Court 6b |

Hard tab not captured; presumed similar pattern with `Hard*` ids.

### Reservation overlay structure
- One `<td id="Clay2" class="fc-resourceid-Clay2">` per court column — spans the entire day
- Each reserved slot is `<div class="fc-event">` with `style.top` / `style.height` pixel offsets
- **Empty hours have no DOM element at all**

### Time-slot rows
- Separate `<table class="fc-agenda-slots">`
- Even-indexed rows have a `<th>` like `"6am"`, `"7am"`, `"12pm"`, `"1pm"`
- Odd-indexed rows are half-hours (no label)

### The algorithm we never finished

To **scan availability**:
1. Get bounding rect of each court's `<td>`
2. Get bounding rect of each `.fc-agenda-slots` row labelled with an hour
3. For each `.fc-event`, find which court column it sits in (horizontal overlap)
   and which hour rows it overlaps (vertical overlap)
4. Available = hours not covered by any event for that court

To **click a (court, hour) cell**:
1. Compute viewport `(x, y)` at the column center × hour row center
2. `page.mouse.click(x, y)`

### Site quirks
- Pre-existing 404 on `/Member/MPIncludes/js/jquery-3.3.1.min.js` (returns
  `Content-Type: text/html` 404 page) sometimes poisons Knockout init and
  prevents the calendar's `#Resource` options from populating. Earlier in a
  session it works; later it stops. Not our bug to fix.
- ServiceWorker registration also fails — disabled in our inspector with
  no improvement.

## Lessons

1. **Inspect first, code second.** Read the live DOM before writing any
   selector. `view-source:` isn't enough — use DevTools or a Playwright
   inspector to see the actual rendered tree (post-JavaScript).
2. **A simulator built from a spec proves nothing.** Our simulator matched
   the bot perfectly; all 25 scenarios were designed to pass; zero would
   have caught the real-site mismatch. Test against fixtures derived from
   the real site, not synthesized HTML.
3. **FullCalendar v1 doesn't render slot cells.** It uses overlay divs with
   absolute pixel positioning. Any automation against it must work in
   coordinates, not in DOM cells.
4. **UX descriptions are not DOM descriptions.** "User clicks an empty
   cell" and "Playwright targets a `<td>` element" describe different things.

## What's salvageable if anyone resurrects this

Layers that don't touch the page work and could be reused:

- Priority list (`config.PRIORITY_LIST`, 44 entries)
- Booker orchestration (`book_courts.py`): date guard, TOCTOU retry, session
  re-login, partial-booking flows
- Email notifier (`notifier.py`)
- Dashboard generator (`dashboard.py`)
- TEST_MODE plumbing (`test_capture.py`)
- CapSolver HTTP shim (`captcha.py`)
- Standalone smoke tests (`test_email.py`, `test_git_push.py`)
- Inspector tool (`tools/inspect_site.py`) — works as far as the calendar
  page; needs more work for the modal/cart pages

What would need a clean rewrite:

- `browser.py`: `scan_availability` + click logic in coordinate space using
  FullCalendar's overlay math (algorithm sketched above)
- `config.SELECTORS`: cell, modal, cart, popup selectors all need real-DOM
  versions
- A fixture-based test suite (replace the simulator entirely)

## Costs

- CapSolver: $0 spent (never solved a real CAPTCHA)
- Gmail App Password, GitHub: free
- Real bookings: 0
- Sunk dev cost: not worth it for the outcome
