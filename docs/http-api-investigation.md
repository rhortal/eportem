# Investigation: replacing Selenium with direct HTTP calls

Status: **implemented behind `EPORTEM_HTTP=YES`, not yet verified with a real
clock event** (2026-11-16, branch `http-clock-actions`). Cron still uses the
Selenium click flow by default. See "Remaining before switching" below.

## Goal

Stop driving a full Chromium session for every clock action
(`eportem_action.py` → `utility/login_and_navigate.py`). Instead, make the
same HTTP requests the ePortem web front end makes when you click a button.

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
- Session cookies set on the login page: `ASP.NET_SessionId`, `ARRAffinity`,
  `ARRAffinitySameSite`, `TiPMix`, `x-ms-routing-name` (Azure App Service).
  The authenticated cookie that login sets (probably `.ASPXAUTH` or similar)
  and its lifetime are **not yet known**.

**Conclusion:** a pure-HTTP login is not possible without bypassing
reCAPTCHA. A captcha-solving service or token spoofing would mean evading
the employer's bot detection, so it is ruled out.

### No alternative API found

- The site is a PWA (`/manifest.json`, `start_url: /aplicaciones`), but
  it's only a wrapper around the same web pages, not a separate API.
  `/sw.js` is 58 bytes. Unknown paths return a 200 "not found" page of about 21.9 KB, so you can't
  find hidden endpoints by guessing paths.

- No public ePortem API documentation or open-source client exists (web and
  GitHub searches).
- No ePortem mobile app turned up that might expose a captcha-free API.
- `/aplicaciones` without a session returns a 302 to the login page.

## Plan: hybrid (Selenium login → `requests` for the action)

1. Log in with Selenium exactly as today (the browser runs reCAPTCHA
   naturally). Consider ticking `recordar` to get a longer-lived session.
2. Copy `driver.get_cookies()` into a `requests.Session` and quit the
   browser.
3. Make the clock action (start / pause / resume / stop, plus the session
   type: home `1293`, office `1`, see `SESSION_ID_*` in `eportem_action.py`)
   as a direct HTTP request. If the request needs an ASP.NET anti-forgery
   token, scrape it from the dashboard HTML with the same session.
4. Optionally save the cookies (`chmod 600`, gitignored) and reuse them on
   later runs. Fall back to a fresh browser login only when the session has
   expired. This would make most runs browser-free.

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

The response is JSON (`isActive`, `LastDescAct`, `listActiv` = the new
buttons' HTML, ...). There is no anti-forgery token. The only auth is the
`.ASPXAUTH` cookie (a session cookie, no expiry attribute) together with
`ASP.NET_SessionId`. According to the page's own message, a clock event
without a location is still recorded ("El fichaje se ha registrado sin
geolocalización"). Headless Selenium most likely sends it empty already.

Buttons on the page while working (2026-11-16): `_stpause` entries
2 Comida, 3 Ausencia, 5916/1190 Vacaciones, 1191 Baja Laboral, 1193 Médico,
1192 Maternidad/Paternidad, 1195 Permiso Retribuido; `_stini` 1293 Trabajo en
Casa; `_ststop` (no `name`). The buttons available depend on the current state.
**The "not started" and "paused" markup hasn't been captured yet.**

### Implementation

`utility/http_clock.py`:
1. Load the cookies from `config/.session_cookies.json` and GET the dashboard.
   If the response is the login page, log in with Selenium (as today) and save
   the new cookies.
2. Parse the clock buttons out of the dashboard and pick the one the Selenium
   XPaths would click (e.g. `lunch_break` → `_stpause` name 2, `after_lunch`
   home → `_stini` 1293). If it's missing (wrong state), raise
   `ButtonNotFound` listing the buttons that are there.
3. Send the GET with that button's attributes, with location and IP left empty.

`python3 -m utility.http_clock ACTION --location L` is a dry run. It resolves
the request against the live dashboard and prints it without sending.
Verified on 2026-11-16 for `lunch_break` and `stop_day` (both match the
captured button attributes exactly). `after_lunch` correctly refused while
working.

### Remaining before switching cron to it

1. **One real `--send`** at a normal clock time (e.g. lunch), to confirm the
   server records it and to see the JSON response. That's the only step that
   changes clock status, so it's left to the user.
2. **Capture the not-started and paused markup** (run
   `utility/capture_dashboard.py` before the day starts and during lunch) to
   confirm the `start_day` office button really is `_ststart` name 1, and that
   paused shows `_stini` 1 / 1293. The tests model them from the Selenium XPaths.
3. **Session lifetime:** run a dry run some hours after the last login and
   see whether it reports "Saved session expired". If `.ASPXAUTH` lasts across
   the day, most runs won't need a browser at all. Ticking `recordar` at login
   may give a longer-lived cookie; not tried yet.
4. Then set `EPORTEM_HTTP=YES` in `config/.env` on `omv`.

## Side risk to the current Selenium setup

reCAPTCHA v3 scores headless browsers low, and the login page's code
suggests the captcha was added fairly recently. If cron logins start failing
silently, look for the "no es un robot" message in the page after
submitting. Neither a selector change nor a Chromium crash produces that
message.

## Environment note (cloud sessions)

`eportem.es` is blocked by default in Claude Code cloud sessions. A personal
cloud environment called **`eportem`** was created with `eportem.es` /
`www.eportem.es` allowed. Use it to resume this work from the cloud.
