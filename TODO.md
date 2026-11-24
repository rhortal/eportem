# To do

Open items for CheckIn on `omv`. Tick them off (or delete the line) when done,
and note anything learnt in `docs/http-api-investigation.md` or `docs/OPERATIONS.md`.

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

## The service (refactor merged into `main` 2026-11-24)

Details for each item are in `docs/HANDOFF.md`.

- [x] 2026-11-18 18:50: contract check against the real site: all PASS.
- [x] 2026-11-18 evening: shadow deployed on `omv` (dry run, sends nothing).
- [x] Shadow reports from 2026-11-19; switched to the service 2026-11-24
      09:30; first full live day clean; `main` fast-forwarded the same evening.
- [ ] About 2026-11-28: delete the old volumes (list in `docs/HANDOFF.md`).
- [ ] About 2026-12-08, after two clean weeks: remove the cron path (PLAN.md
      phase 8, step 6).
- [x] `checkin.hortal.me`: a Cloudflare DNS record and an nginx-proxy-manager
      proxy host (found in place on 2026-11-21, see `docs/HANDOFF.md`).
- [x] A destination for GlitchTip alerts (Telegram) and an outside uptime
      monitor on `https://checkin.hortal.me/healthz` (Montastic), 2026-11-21.
- [x] GlitchTip moved out of this project's Compose project into its own stack on
      a shared Postgres, for every service on the host (2026-11-21).
- [ ] The owner's region for public holidays (only national ones for now).
- [ ] Make CheckIn multilingual (added 2026-11-21). Today only the web UI is
      translated, English and Spanish, from a hand-written dictionary in
      `checkin/web/i18n.py` (English text as keys, missing entries fall back to
      English); `default_locale` and each user's `locale` only allow `en`/`es`.
      Still English-only: Telegram/Slack notifications and alerts (sent by the
      scheduler), emails, API error messages and the CLI. To work out: a real
      message catalogue (gettext/Babel or similar) instead of the dictionary,
      sending each person's notifications in their own language, a test that
      fails on untranslated UI text, and which languages to add (Catalan,
      Basque and Galician are the obvious next ones for Spain).
