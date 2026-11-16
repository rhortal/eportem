# Replacing Selenium with direct HTTP calls

Branch `http-clock-actions`. This document is the handoff: it holds everything
needed to pick the work up in a new session, without the earlier conversation.

## Handoff: state as of 2026-11-16 11:05 (Monday)

### All actions over HTTP, with fallback in the orchestrator (deployed 2026-11-16 14:57)

`run_http.sh` is gone. The choice between HTTP and Selenium now lives in
`EPortemAction.perform()`, which `main.py` calls **after** it has applied
the schedule, holidays and the location / business-trip overrides. So the
overrides hold whichever way an action is sent, and cron goes back to calling
`run.sh` for every line.

- `EPORTEM_HTTP` in `config/.env` picks the actions sent over HTTP: `YES`/`ALL`,
  `NO`/unset, or a list such as `lunch_break,after_lunch`.
- `HttpClock.clock_and_verify()` returns on success, raises `NotRecorded`
  (falling back to Selenium in the same run is safe) or `OutcomeUnknown`
  (no fallback, the run fails so cron mails). Any other error also fails
  without fallback.
- Every HTTP attempt still goes to `logs/http_clock.log`, now as
  `=== date action location: outcome` followed by the HTTP client's output
  (including the `Session:` line).

**On `omv` since 2026-11-16 14:57:** `config/.env` has `EPORTEM_HTTP=YES`
(all four actions), and the 13:25 line calls `run.sh` again like every other
line (crontab before this change: `/home/pi/crontab.bak-20261116-run_http`).
The 14:25 after-lunch run predates the deploy and used Selenium; the first
run on the new path is 17:55 (stop).
The first `start_day` over HTTP is Tuesday 2026-11-17 08:55; its office button
was a guess until the 18:30 capture, and if it's wrong the run falls back to
the browser (check `logs/http_clock.log`).

The rest of this section describes `omv` as it was before that change.

### What is live on `omv`

- `/home/pi/Apps/eportem` is checked out on **`http-clock-actions`** (not
  `main`). The branch is a superset of `main`, and with `EPORTEM_HTTP` unset,
  `run.sh` behaves exactly as on `main`.
- **Only the lunch cron line uses HTTP**:
  `25 13 * * 1-5 ... /home/pi/Apps/eportem/run_http.sh lunch_break office`
  (same random 0–9 min sleep and mail-on-failure wrapper as the other lines).
  Start, after-lunch and stop still call `run.sh`, i.e. Selenium.
  The previous crontab is saved in `/home/pi/crontab.bak-20261116-102837`.
- `config/.env` on `omv` does **not** set `EPORTEM_HTTP`; `run_http.sh` calls
  `utility.http_clock` directly, so it doesn't need it.
- Saved session: `config/.session_cookies.json` on `omv`, created by a
  browser login at **10:27**. It was last used by a dry run at about **10:56**.
  On purpose, nothing has used it since, so the lunch run measures how long a
  session lasts.
- `at` was installed on 2026-11-16 for one-off jobs. Two jobs are queued for
  today, see below. `atq` lists them.

### Today's timeline (2026-11-16)

| Time | Job | Purpose |
|---|---|---|
| 13:25–13:35 | cron `run_http.sh lunch_break office` | **First real HTTP clock event.** Falls back to `run.sh` only if nothing was recorded. |
| ~~14:00~~ 13:40 | `utility.capture_dashboard`, run by hand (the 14:00 `at` job was removed) | **Done**: `capture/20261116-134022/`, paused dashboard. Confirms lunch was recorded. |
| 14:25–14:35 | cron `run.sh` (Selenium) | After lunch. It fails if lunch wasn't recorded. |
| 17:55–18:05 | cron `run.sh` (Selenium) | End of day. |
| 18:30 | `at` job: `utility.capture_dashboard` | Captures the **stopped / not started** dashboard. |

### How to check the results (after 18:30; the paused capture is done)

From the Mac, `omv` is reachable as **`omve`** (external address). Use
`omv` only on the home LAN.

```bash
ssh omve 'cd /home/pi/Apps/eportem && cat logs/http_clock.log; tail -20 logs/capture.log; ls capture/'
# each capture folder: buttons.html (read this first), hits.txt, cookies.json (names only),
# session_check.txt, dashboard.html, scripts/
ssh omve 'cd /home/pi/Apps/eportem/capture && for d in */; do echo "== $d"; grep -o "id=\"_st[a-z]*\"[^>]*" $d/buttons.html; done'
```

Also check that cron didn't send a failure mail (it mails `pi` and the
work address only when a run exits non-zero).

**Reading `logs/http_clock.log`** (one block per attempt, `=== date action location exit=N`):
- `exit=0` plus `Response: {...}`: recorded over HTTP. Note the JSON's
  `LastDescAct`; it should be "Comida".
- `exit=3`: nothing was recorded over HTTP, so it fell back to Selenium. The
  first line says why (`ButtonNotFound`, login failure, ...). Check the cron
  mail and the ePortem dashboard to see whether the Selenium fallback worked.
- `exit=4`: the request went out but the outcome is unknown, so it **did not**
  retry. Check the dashboard by hand.
- `exit=5`: recorded, but notifications or Slack status failed.
- The `Session:` line is a **session-lifetime data point**: "still valid
  (login HH:MM, XhYYm ago; last used ...)" or "expired (...)". On this first
  run "last used" shows as unknown because the file predates that field; the
  real last use was about 10:56. Add the result to the table under
  "Session lifetime" below.

### What to do next, depending on the results

1. **Confirm the button choices against the captures.** `select_button()` in
   `utility/http_clock.py` picks:
   - `start_day` office: `_ststart` name `1`, else the first `_ststart` that
     isn't `1293`. *Assumed, not yet seen.* The Selenium XPath for this is a
     plain button, `//*[@id="buttonsRegBox"]/div/div/button`, so check in the
     18:30 capture that the office start button really has `id="_ststart"`
     and an `onclick="_doPostJor(this)"`. If it doesn't, fix
     `select_button()` and the `NOT_STARTED_HTML` fixture in
     `tests/test_http_clock.py`.
   - `start_day` home: `_ststart` name `1293`.
   - `after_lunch`: `_stini` name `1` (office) or `1293` (home).
     **Confirmed** by the 13:40 capture (`capture/20261116-134022/`): the paused
     dashboard shows `_stini` name `1` (name3 "Trabajo") and `1293` ("Trabajo
     en Casa"), plus `_ststop` and seven `_stpause` absence types. The
     `PAUSED_HTML` fixture's name3 was corrected from "Inicio Trabajo" to
     "Trabajo" to match.
   - `lunch_break`: `_stpause` name `2` (Comida). *Verified.*
   - `stop_day`: `_ststop` (no `name`). *Verified* from markup.
2. **Lunch worked over HTTP (2026-11-16).** Add actions to
   `EPORTEM_HTTP` in `config/.env` on `omv`; the crontab doesn't change.
   `main.py` supplies the location, holidays and overrides.
3. **If lunch failed:** read the log and the capture. The fallback should
   have recorded it through Selenium, so check that first.
4. When everything has been on HTTP for a while, merge `http-clock-actions`
   into `main` and switch `omv` back to `main`.
5. Clean up: the captures in `capture/` hold account data and can be
   deleted once read.

### Known gaps / open questions

- **Holidays and overrides: solved** by moving the HTTP/Selenium choice
  into `EPortemAction.perform()`, after `main.py`'s checks (see the top of
  this handoff). Before that, `run_http.sh` skipped them, which would have
  clocked `start_day` in on a holiday.
- **Session lifetime is only partly known.** `.ASPXAUTH` has no expiry
  attribute. So far a session survived 3h06m after login with ~2h38m idle
  (see the data points below); the real server-side timeout, and whether it
  slides, are still unknown. Ticking `recordar`
  ("remember me") at login may give a longer-lived cookie; not tried yet.
- The 15-minute schedule window in `main.py` applies to HTTP actions too.

### Session lifetime data points

| Date | Login | Checked | Idle since last use | Result |
|---|---|---|---|---|
| 2026-11-16 | 10:13 (Mac) | 11:00 | ~0h46m | valid |
| 2026-11-16 | 10:27 (omv) | lunch run, 13:34 | ~2h38m (last use ~10:56) | valid (3h06m after login); lunch recorded over HTTP, `exit=0` |

### How to deploy changes to `omv`

Gitea (`origin` on `omv`) is **not reachable from the Mac**; only `omv`
can reach it. The Mac clone's `origin` is GitHub, which is a **push mirror**
of Gitea, so don't push to GitHub directly: the next mirror sync overwrites
it. Deploy from the Mac like this:

```bash
git push omve:/home/pi/Apps/eportem http-clock-actions:refs/heads/incoming
ssh omve 'cd /home/pi/Apps/eportem && git merge --ff-only incoming && git branch -D incoming && git push origin http-clock-actions'
```

You can't push straight to `http-clock-actions` on `omv` because it's
checked out there. Gitea's push mirror to `github.com/rhortal/eportem` syncs
on commit and every 8 h. Check it with
`gt api /api/v1/repos/roberto/eportem/push_mirrors` (look at `last_error`).

Tests: `python3 -m unittest tests/test_*.py` (or `run_tests.sh`). They never
touch the network or the real cookie file. Dry runs
(`python3 -m utility.http_clock ACTION --location L`) never record a clock
event. Only `--send`, or `EPORTEM_HTTP` enabling an action for
`main.py`/`eportem_action.py`, do. **Don't run a dry run on `omv` before a cron run you
want to measure**, because it refreshes the session.

### Repository history was rewritten on 2026-11-16

Old example values shaped like Slack and Telegram bot tokens were scrubbed
from **all** branches with `git filter-repo`. GitHub push protection had
been blocking the Gitea → GitHub mirror since 2026-10-25. Every commit hash
from May 2025 onwards changed (e.g. `main` `f7c3fa7` → `a96920c`). Any clone
made before that needs a fresh clone. Backups of the pre-rewrite refs (they
still contain the values) are in `/home/pi/backups/` on `omv`, `chmod 600`.
If those tokens were ever real, they should be revoked: they were public on
GitHub from May 2025.

## Findings

### Login is protected by reCAPTCHA v3 (server-verified)

`GET https://eportem.es/Usuario/Login?ReturnUrl=%2faplicaciones` serves a
plain ASP.NET (IIS, `X-AspNet-Version: 4.0.30319`) form:

```
<form method="post" id="login-form">
  cc=             (hidden; "false" on a normal submit)
  recaptchaToken= (hidden; filled by grecaptcha.execute(..., {action: 'login'}))
  usuario=        (upper-cased on blur)
  password=
  recordar=       (checkbox, "remember me")
```

- The page loads `https://www.google.com/recaptcha/api.js?render=<site key>`
  and fetches a token on page load, every 90 s, and when a field gets focus.
  The token expires after about 2 minutes. An inline comment says the real
  check happens server-side (`RecaptchaHelper.cs`).
- **Verified:** a `requests`-style POST with an empty `recaptchaToken` and a
  made-up username returns 200 with the error *"No se ha podido verificar que
  no es un robot. Recargue la página e inténtelo de nuevo."* The captcha is
  checked before the credentials.
- Cookies after login: `.ASPXAUTH` (the auth ticket), `ASP.NET_SessionId`,
  `ARRAffinity`, `ARRAffinitySameSite`, `TiPMix`, `x-ms-routing-name` (Azure
  App Service) and `gfTipoLogin`. `.ASPXAUTH` and `ASP.NET_SessionId` are
  session cookies with no expiry attribute.
- `utility/login_and_navigate.py` (`create_driver`) makes headless Chrome
  look like a desktop browser and waits for reCAPTCHA when the page loads it.
  That is what gets the cron logins past it.

**Conclusion:** a pure-HTTP login is not possible without bypassing
reCAPTCHA. A captcha-solving service or token spoofing would mean evading
the employer's bot detection, so it is ruled out. The browser logs in, and
HTTP does the rest.

### No alternative API found

- The site is a PWA (`/manifest.json`, `start_url: /aplicaciones`), but
  it's only a wrapper around the same web pages, not a separate API.
  `/sw.js` is 58 bytes. Unknown paths return a 200 "not found" page of about
  21.9 KB, so you can't find hidden endpoints by guessing paths.
- No public ePortem API documentation or open-source client exists (web and
  GitHub searches).
- No ePortem mobile app turned up that might expose a captcha-free API.

### Clock endpoint (captured 2026-11-16)

Found with `utility/capture_dashboard.py`. It's a read-only capture: it logs in
and saves the page, scripts and cookie names, without clicking anything. Every
button in `#buttonsRegBox` has `onclick="_doPostJor(this)"`, defined in
`/Content/js/reghorjor1.3.js`. That function first gets the browser's location
(the dashboard sets `_geoRequerida = true`), then sends:

```
GET /aplicaciones/e-portem/registro/reghorario.cshtml
    ?action=<button id>        _ststart / _stpause / _stini / _ststop
    &_codactiv=<name attr>     activity id, e.g. 2 Comida, 1293 Trabajo en Casa
    &_tipoactiv=<name2 attr>   W work / P pause
    &_descactiv=<name3 attr>   label, e.g. "Comida"
    &_geolocation=<lat,lon>    empty when location is unavailable/denied
    &_localip=<WebRTC ip>      empty or an mDNS name in current browsers
```

**It's a GET**, so never request this URL while exploring: it records a clock
event. The response is JSON (`isActive`, `LastDescAct`, `listActiv` = the new
buttons' HTML, ...). There is no anti-forgery token. The only auth is the
cookies. According to the page's own message, a clock event without a
location is still recorded ("El fichaje se ha registrado sin geolocalización").
Headless Selenium most likely sends it empty already.

Buttons on the page while working (2026-11-16): `_stpause` entries
2 Comida, 3 Ausencia, 5916/1190 Vacaciones, 1191 Baja Laboral, 1193 Médico,
1192 Maternidad/Paternidad, 1195 Permiso Retribuido; `_stini` 1293 Trabajo en
Casa; `_ststop` (no `name`, `name2="P"`, `name3="Inicio Trabajo"`). The buttons
available depend on the current state. The paused and not-started markup is
being captured on 2026-11-16 (see the timeline above).

## Implementation

- **`utility/http_clock.py`**
  1. Loads `config/.session_cookies.json` (gitignored, `chmod 600`; it holds
     `logged_in_at`, `last_used_at` and the cookies) and GETs the dashboard.
     If the response is the login page, it logs in with Selenium through
     `login_and_navigate()` and saves the new cookies. Each run prints a
     `Session:` line with the session's age.
  2. Parses the clock buttons and picks the one the Selenium XPaths would
     click (`select_button()`). If that button is missing (wrong state), it
     raises `ButtonNotFound` listing the buttons present.
  3. With `--send`, it sends the GET with that button's attributes. If the
     send fails, it re-reads the dashboard to tell "recorded" from "not
     recorded".
  - `clock_and_verify()` does steps 1-3 and raises `NotRecorded` (safe to
    fall back) or `OutcomeUnknown` (don't retry).
  - CLI exit codes, for runs by hand: `0` recorded, `3` nothing recorded,
    `4` unknown (check by hand), `5` recorded but notifications failed.
    `--notify` sends the usual Telegram/Slack messages and Slack status via
    `EPortemAction.after_action()`.
- **`EPORTEM_HTTP`** (`YES`, `NO` or a list of actions) makes
  `EPortemAction.perform()` try HTTP first for those actions and fall back
  to clicking only on `NotRecorded`. Each attempt is logged to
  `logs/http_clock.log`.
- **`utility/capture_dashboard.py`**: the read-only capture (see above).
  Output goes to `capture/<timestamp>/` (gitignored).

## Environment note (cloud sessions)

`eportem.es` is blocked by default in Claude Code cloud sessions. A personal
cloud environment called **`eportem`** was created with `eportem.es` /
`www.eportem.es` allowed. Cloud sessions can't reach `omv` or Gitea, though,
so checking today's results needs a local session on the Mac.
