# Replacing Selenium with direct HTTP calls

Merged into `main` on 2026-11-16 (the work was done on the branch
`http-clock-actions`). This document is the handoff: it holds everything
needed to pick the work up in a new session, without the earlier conversation.

## Handoff: state as of 2026-11-16 15:05 (Monday)

### What is live on `omv`

- `/home/pi/Apps/eportem` is on **`main`**. `config/.env` has
  **`EPORTEM_HTTP=YES`** (since 14:57), so all four actions are sent over HTTP.
- Every cron line calls `run.sh` → `main.py`, which applies the schedule,
  holidays and location / business-trip overrides, then calls
  `EPortemAction.perform()`. That tries HTTP and falls back to Selenium in the
  same run only when nothing was recorded (`NotRecorded`). If the outcome is
  unknown (`OutcomeUnknown`) or there's an unexpected error, the run fails
  without a fallback, so nothing is clocked twice, and cron mails the output.
- Crontab backups: `/home/pi/crontab.bak-20261116-102837` (before any HTTP)
  and `/home/pi/crontab.bak-20261116-run_http` (lunch line on the old
  `run_http.sh`, removed in `ac9aefb`).
- Saved session: `config/.session_cookies.json`, browser login at 10:27, last
  used at 15:02 (a read-only dashboard check).
- `at` (installed 2026-11-16) has one job left: the 18:30
  `utility.capture_dashboard` run. `atq` lists it.

### Review changes of 2026-11-16: in the working tree, not committed or deployed

A full review on the afternoon of 2026-11-16 changed most files. Until these
are committed and deployed, `omv` still runs `fd05812`, and everything else
in this handoff describes that version. What changes once they are deployed:

- **Outcome checks** (`utility/http_clock.py`). A 200 answer only counts as
  recorded if it is a clock result (it has `isActive`, `LastDescAct` or
  `listActiv`). After a failed or odd answer the dashboard is read up to 3
  times, 5 s apart. A page without `buttonsRegBox`, or with no buttons, is
  "can't tell" (`OutcomeUnknown`), no longer "recorded". A read timeout or a
  dropped connection with the button still offered is also `OutcomeUnknown`;
  only "never connected" or an HTTP error status is `NotRecorded`.
- **Session file.** Written atomically; a corrupt one is replaced after a
  browser login instead of forcing Selenium for ever. It also stores the
  login browser's `user_agent`, which the HTTP requests now really send
  (before, they went out as `python-requests`).
- **Login.** A rejected login raises `LoginRejected` with the reason
  (reCAPTCHA, or still on the login page). The browser is always closed when
  a login fails. One run submits the login form at most 4 times on the
  Selenium path, plus 1 on the HTTP path.
- **`lunch_break`** sends only `_stpause` name `2` (Comida); the fallback to
  the first pause on offer is gone.
- **Notifications** can't fail a run any more (see README, "When a
  notification fails"), have a 15 s timeout, and never print a token.
- **`main.py`** exits 3 outside every window and 2 for an invalid config or
  holiday file; `./run.sh --check` shows what would run. Override files and
  the config are found relative to the repository, whatever the current
  directory.
- **`run.sh`** takes a `flock` lock (exit 75 if held) and has `--install`.
- **`requirements.txt`** is pinned to what `omv`'s venv already has, so
  deploying doesn't trigger a reinstall.

Things to know when deploying:

- Don't deploy between a cron line firing and its run finishing. The safest
  moment is mid-morning or mid-afternoon.
- The live crontab was checked: every line lands inside its window, so exit 3
  should never fire. If a cron mail with "No action matches the current time"
  arrives, a crontab line is wrong.
- After deploying, run `./run.sh --check` on `omv`. It validates the config
  and override files and clocks nothing.
- The first run after the deploy rewrites `config/.session_cookies.json` in
  the new format. The old format still loads.
- `logs/` on `omv` is `755` with `644` files; the first HTTP attempt after
  the deploy tightens it to `700`/`600`.
- Not done, needs a decision: deleting `feature/user-auth-and-multiuser` on
  Gitea (and so on the GitHub mirror). Its history holds a sample `.jwt` file
  with an email claim (commits `9c104b8`, `414b842`), default signing
  secrets, and a debug server bound to `0.0.0.0`. It is the only place the
  `.jwt` file is reachable from.
- Small leftovers on `omv`: `USE_MOCK_SERVER` is still in `config/.env`
  (nothing reads it), and the comment above the first ePortem crontab line is
  out of date.

### Open checks

| When | What runs | What to check |
|---|---|---|
| 2026-11-16 17:55–18:05 | `stop_day` | **First action on the new path.** Expect `stop_day office: recorded over HTTP` in the log. The `Session:` line is a lifetime data point (idle since 15:02). |
| 2026-11-16 18:30 | `at` capture | The **not-started** dashboard. Confirms or corrects the office start button (see below). |
| 2026-11-17 08:55–09:05 | `start_day` | **First `start_day` over HTTP**, and almost certainly the first overnight session expiry, so it should log in with the browser first. Expect `Session: saved session expired ...` then `recorded over HTTP`. A fallback means the office start button was guessed wrong. |
| 2026-11-17 13:25, 14:25 | lunch, after lunch | First `after_lunch` over HTTP. |

**The office start button is still a guess.** `select_button()` picks
`_ststart` name `1`, else the first `_ststart` that isn't `1293`. The
Selenium XPath is a plain button, `//*[@id="buttonsRegBox"]/div/div/button`,
so check in the 18:30 capture that the office start button really has
`id="_ststart"` and `onclick="_doPostJor(this)"`. If it doesn't, fix
`select_button()` and the `NOT_STARTED_HTML` fixture in
`tests/test_http_clock.py`. Until then a wrong guess costs nothing: it raises
`ButtonNotFound` and the run falls back to the browser.

### How to check

From the Mac, `omv` is reachable as **`omve`** (external address). Use
`omv` only on the home LAN.

```bash
ssh omve 'cd /home/pi/Apps/eportem && tail -60 logs/http_clock.log; tail -20 logs/capture.log; ls capture/'
# each capture folder: buttons.html (read this first), hits.txt, cookies.json (names only),
# session_check.txt, dashboard.html, scripts/
ssh omve 'cd /home/pi/Apps/eportem/capture && for d in */; do echo "== $d"; grep -o "id=\"_st[a-z]*\"[^>]*" $d/buttons.html; done'
```

Also check that cron didn't send a failure mail (it mails `pi` and the
work address only when a run exits non-zero). To see the dashboard state
without clicking anything, `HttpClock().ensure_session()` returns the
buttons on offer (note: that refreshes the session's "last used" time).

**Reading `logs/http_clock.log`.** Each attempt is one block:
`=== date action location: outcome`, then the HTTP client's output.

- `recorded over HTTP`: done. The `Response: {...}` JSON's `LastDescAct`
  names the new state.
- `not recorded, falling back to the browser: <reason>`: Selenium ran next
  in the same run. Check the cron mail and the dashboard to see whether it
  worked.
- `OUTCOME UNKNOWN` or `ERROR, no fallback`: the run failed on purpose.
  Check the dashboard by hand and correct it in Registro Jornada.
- The `Session:` line is a **session-lifetime data point**: "still valid
  (login HH:MM, XhYYm ago; last used HH:MM, ...)" or "expired (...)". Add it
  to the table under "Session lifetime data points".

Blocks before 14:57 on 2026-11-16 are in the older `run_http.sh` format
(`=== date action location exit=N`).

### Button choices (`select_button()` in `utility/http_clock.py`)

- `start_day` office: `_ststart` name `1`, else the first `_ststart` that
  isn't `1293`. *Assumed*, see "Open checks".
- `start_day` home: `_ststart` name `1293`.
- `lunch_break`: `_stpause` name `2` (Comida). **Verified**: recorded over
  HTTP at 13:34 on 2026-11-16.
- `after_lunch`: `_stini` name `1` (office, name3 "Trabajo") or `1293`
  (home, "Trabajo en Casa"). **Confirmed** by the 13:40 capture
  (`capture/20261116-134022/`).
- `stop_day`: `_ststop` (no `name`). Seen on the working and paused
  dashboards.

### Next steps, after the open checks

1. Fix `select_button()` if the 18:30 capture or the 08:55 run shows the
   office start button is different.
2. Delete the captures in `capture/` on `omv` once read: they hold account
   data.
3. Delete the two crontab backups once a few days have run cleanly.
4. Optional: try ticking `recordar` ("remember me") at login for a longer
   session, which would cut the morning browser logins.

### Rollout history (2026-11-16)

| Time | Event |
|---|---|
| 10:27 | Browser login on `omv`, session saved. |
| 13:34 | **First real HTTP clock event**: lunch, via the old `run_http.sh` cron line. Recorded (`LastDescAct` "Comida"). |
| 13:40 | Paused-dashboard capture by hand (the 14:00 `at` job was removed). Confirmed the `after_lunch` buttons. |
| 14:28 | After lunch, still via Selenium (it predates the deploy). |
| 14:57 | Deployed `ac9aefb`: HTTP/Selenium choice moved into `EPortemAction.perform()`, `run_http.sh` removed, `EPORTEM_HTTP=YES`, lunch cron line back on `run.sh`. |
| 15:02 | Read-only dashboard check: working, in the office. Session still valid. |
| 15:05 | Merged into `main`; `omv` switched to `main`. |

### Known gaps / open questions

- **Session lifetime is only partly known.** `.ASPXAUTH` has no expiry
  attribute. So far a session survived 4h35m after login, with idle gaps of
  up to ~2h38m (see the data points below); the real server-side timeout, and
  whether it slides, are still unknown. Ticking `recordar` ("remember me")
  at login may give a longer-lived cookie; not tried yet.
- The 15-minute schedule window in `main.py` applies to HTTP actions too.
- The `utility.http_clock` CLI (for runs by hand) skips the schedule,
  holiday and override checks; only `main.py` applies them.

### Session lifetime data points

| Date | Login | Checked | Idle since last use | Result |
|---|---|---|---|---|
| 2026-11-16 | 10:13 (Mac) | 11:00 | ~0h46m | valid |
| 2026-11-16 | 10:27 (omv) | lunch run, 13:34 | ~2h38m (last use ~10:56) | valid (3h06m after login); lunch recorded over HTTP |
| 2026-11-16 | 10:27 (omv) | dashboard read by hand, 15:02 | 1h28m (last use 13:34) | valid (4h35m after login) |

### How to deploy changes to `omv`

Gitea (`origin` on `omv`) is **not reachable from the Mac**; only `omv`
can reach it. The Mac clone's `origin` is GitHub, which is a **push mirror**
of Gitea, so don't push to GitHub directly: the next mirror sync overwrites
it. Deploy from the Mac like this:

```bash
git push omve:/home/pi/Apps/eportem main:refs/heads/incoming
ssh omve 'cd /home/pi/Apps/eportem && git merge --ff-only incoming && git branch -D incoming && git push origin main'
```

You can't push straight to `main` on `omv` because it's checked out there.
Gitea's push mirror to `github.com/rhortal/eportem` syncs on commit and every
8 h. Check it with `gt api /api/v1/repos/roberto/eportem/push_mirrors` (look
at `last_error`).

Tests: `python3 -m unittest discover -s tests -t .` (or `run_tests.sh`). They
never touch the network or the real cookie file. `test_eportem` takes about
2½ minutes because its Selenium tests really sleep between clicks. Dry runs
(`python3 -m utility.http_clock ACTION --location L`) never record a clock
event. Only `--send`, or `EPORTEM_HTTP` enabling an action for
`main.py`/`eportem_action.py`, do. **Don't run a dry run on `omv` before a
cron run you want to measure**, because it refreshes the session.

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
available depend on the current state. The paused dashboard (13:40 capture)
offers `_stini` 1 Trabajo and 1293 Trabajo en Casa, `_ststop` and the same
seven `_stpause` absence types. The not-started markup is captured at 18:30
on 2026-11-16.

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
