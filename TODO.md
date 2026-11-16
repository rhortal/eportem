# To do

Open items for ePortem on `omv`. Tick them off (or delete the line) when done,
and note anything learnt in `docs/http-api-investigation.md` or `CLAUDE.md`.

## Housekeeping on `omv` (once a few days have run cleanly after 2026-11-16)

- [ ] Delete `capture/` (dashboard captures from 2026-11-16; they hold account
      data). Read the 18:30 capture first, see below.
- [ ] Delete the crontab backups `/home/pi/crontab.bak-20261116-*`.
- [ ] Remove the `USE_MOCK_SERVER` line from `config/.env` (nothing reads it).
- [ ] Fix the comment above the first ePortem line in the crontab
      ("Lunch over HTTP ... falling back to run.sh"): every line calls
      `run.sh`.

## Open checks from the HTTP rollout

- [x] 2026-11-16 18:30 `at` capture: office start button confirmed
      (`_ststart` name `1`); the fallback to another `_ststart` was removed.
- [ ] 2026-11-17 08:55 `start_day`: first `start_day` over HTTP, and likely
      the first browser login after an overnight session expiry. Expect
      `Session: saved session expired` then `recorded over HTTP` in
      `logs/http_clock.log`.
- [ ] Session lifetime: try ticking `recordar` ("remember me") at login for a
      longer-lived session, which would cut the morning browser logins. Add the
      result to the session data points in `docs/http-api-investigation.md`.
