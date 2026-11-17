# To do

Open items for ePortem on `omv`. Tick them off (or delete the line) when done,
and note anything learnt in `docs/http-api-investigation.md` or `CLAUDE.md`.

## Open checks from the HTTP rollout

- [x] 2026-11-16 18:30 `at` capture: office start button confirmed
      (`_ststart` name `1`); the fallback to another `_ststart` was removed.
- [x] 2026-11-17 08:55 `start_day`: recorded over HTTP at 08:57:17 after a
      browser login (session expired 22h29m after login, idle 14h58m). Telegram,
      Slack notification (bot route) and Slack status all sent.
- [x] 2026-11-17 13:25 / 14:25: `lunch_break` at 13:25:07 and the first
      `after_lunch` at 14:27:03, both over HTTP.
- [x] 2026-11-17 18:40: first `--verify-day` on a day whose actions were all
      run by the new code: "Day check OK", no alert. Host housekeeping from the
      rollout (captures, crontab backups, the fake log block, `USE_MOCK_SERVER`,
      the stale crontab comment) was done the same evening.
- [ ] Session lifetime: try ticking `recordar` ("remember me") at login for a
      longer-lived session, which would cut the morning browser logins. Add the
      result to the session data points in `docs/http-api-investigation.md`.
