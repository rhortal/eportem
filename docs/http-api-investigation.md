# Investigation: replacing Selenium with direct HTTP calls

Status: **paused, nothing implemented yet** (2026-11-16). This records what
was found so the work can be picked up later.

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

### Blocker: the clock endpoints are unknown

The buttons (`#_ststart`, `#_stpause`, `#_stini`, `#_ststop` inside
`#buttonsRegBox`) live on the authenticated dashboard. The request they send
(URL, method, parameters, anti-forgery token) cannot be seen without logging
in. Next step is a **capture script run once on the host** with real
credentials:

- Launch Chromium with `goog:loggingPrefs = {"performance": "ALL"}`, log in
  via `login_and_navigate(driver)`, then save:
  - the dashboard HTML, especially the buttons' `onclick` / `data-*` /
    `href` attributes and any hidden `__RequestVerificationToken`,
  - every script the dashboard loads (inline and external), searched for
    `$.ajax`, `$.post` and `url:`, and for the `_st*` ids,
  - the cookie **names** and expiry times (never the values),
  - the `Network.requestWillBeSent` events from the performance log, with
    the password and cookie values redacted.
- Reading the HTML and scripts is enough to find the endpoint **without
  clicking anything**. Only if that fails, add a `--click ACTION` mode that
  records one real action. Run that at the normal clock time, because it
  registers a real clock event.

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
