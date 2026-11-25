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
      proxy host (found in place on 2026-11-21, see `docs/HANDOFF.md`). Since
      2026-11-25 the app is `checkin-app.hortal.me` and `checkin.hortal.me` is the
      website on Cloudflare Pages.
- [x] 2026-11-25: CheckIn from AI agents (D-028) merged and live on `omv`; the website
      presents it (deployed with `website/deploy.sh`, now possible from the work Mac).
- [ ] Rename the agent token "Agent: Claude Code on personal laptop (eportem repo)": it
      is on the work Mac (`checkin.py logout`, then `login --name ...`).
- [x] A destination for GlitchTip alerts (Telegram) and an outside uptime
      monitor (Montastic), 2026-11-21; now on `https://checkin-app.hortal.me/healthz`.
- [x] GlitchTip moved out of this project's Compose project into its own stack on
      a shared Postgres, for every service on the host (2026-11-21).
- [ ] The owner's region for public holidays (only national ones for now).
- [ ] Make the rest of CheckIn multilingual (added 2026-11-21). The web UI and the
      public website speak English, Spanish and Catalan from JSON catalogues in
      `checkin/locales/` (D-029, 2026-11-25), with tests that fail on a missing
      key or untranslated UI text. Still English only: Telegram/Slack
      notifications and alerts (written in `checkin/core/actions.py` and the
      scheduler, shared with the cron scripts until they go), emails, API error
      messages (the problems shown on forms too) and the CLI. Next languages for
      Spain: Basque and Galician (a catalogue each, plus the website pages).
