# To do

Open items for ePortem on `omv`. Tick them off (or delete the line) when done,
and note anything learnt in `docs/http-api-investigation.md` or `CLAUDE.md`.

## Housekeeping on `omv` (once a few days have run cleanly after 2026-11-16)

- [ ] Delete `capture/` (dashboard captures from 2026-11-16; they hold account
      data). Read the 18:30 capture first, see below.
- [ ] Delete the crontab backups `/home/pi/crontab.bak-20261116-*`.
- [ ] Delete the fake `2026-11-16 19:32:17 start_day` block (2 lines) from
      `logs/http_clock.log`: a test run during that deploy wrote it (nothing was
      clocked; `actions.log` and the 08:57 response, `idActAnterior: 0`, agree).
- [ ] Remove the `USE_MOCK_SERVER` line from `config/.env` (nothing reads it).
- [ ] Fix the comment above the first ePortem line in the crontab
      ("Lunch over HTTP ... falling back to run.sh"): every line calls
      `run.sh`.

## Open checks from the HTTP rollout

- [x] 2026-11-16 18:30 `at` capture: office start button confirmed
      (`_ststart` name `1`); the fallback to another `_ststart` was removed.
- [x] 2026-11-17 08:55 `start_day`: recorded over HTTP at 08:57:17 after a
      browser login (session expired 22h29m after login, idle 14h58m). Telegram,
      Slack notification (bot route) and Slack status all sent.
- [ ] 2026-11-17 13:25 / 14:25: lunch, then the first `after_lunch` over HTTP.
- [ ] 2026-11-17 18:40: first `--verify-day` on a day whose actions were all
      run by the new code (no alert expected).
- [ ] Session lifetime: try ticking `recordar` ("remember me") at login for a
      longer-lived session, which would cut the morning browser logins. Add the
      result to the session data points in `docs/http-api-investigation.md`.
