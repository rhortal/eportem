# Handoff

Where the work stands and how to pick it up, for the next session or another
machine. This file holds host-specific details (host names, paths, logins), so
the portability test skips it, like `docs/OPERATIONS.md` and `TODO.md`. Update it at the
end of each session. General guidance lives in `CLAUDE.md`, the live host in
`docs/OPERATIONS.md`, the plan in
`docs/refactor/PLAN.md`, the decisions in `docs/refactor/DECISIONS.md`.

## Shadow check (2026-11-21)

- `shadow-report --days 4` exits 0: 2026-11-19 and 2026-11-20 match cron on
  every action, location and minute (the 18th is imported history). One more
  working day (Monday 2026-11-23) makes the 3 the plan asks for.
- `omv` rebooted at 08:02 on 2026-11-19 (unplanned). The service came back
  (`unless-stopped`) and planned and ran the day. The fake had no restart
  policy and has been down since (exit 255); a dry run never contacts the
  target, so it didn't matter. `docker-compose.yml` now restarts it too; it
  comes back on the next update of the shadow.
- Watchtower restarts GlitchTip and its Postgres (now the shared `postgres`) around 04:00 when their pinned
  major tags get a new image (Postgres 18.7 on 2026-11-21). That gives a few
  failed heartbeat pings and error-report retries in the service log at that
  time (seen 2026-11-19 04:05). Harmless; the service's own image has
  Watchtower disabled.
- The out-of-memory kill in the host's kernel log on 2026-11-20 11:13 was
  `immich_machine_learning`, not ePortem.
- The service logs JSON to `docker logs eportem-eportem-1`;
  `docker logs --since` returned nothing for it on 2026-11-21, so read the
  whole log and filter.

## Public hostname: done (found 2026-11-21)

- `checkin.hortal.me` already had a proxied CNAME to `hortal.me` in Cloudflare
  and an nginx-proxy-manager host (`proxymanager`, `proxy_host/73.conf`) to
  `http://eportem-eportem-1:8080` with a Let's Encrypt certificate and Force
  SSL, added after 2026-11-18. Nothing was written to DNS or the proxy.
- Checked from outside: `/healthz` 200 (GET and HEAD), `/readyz` ready, `/login`
  200, `/` and `/admin` redirect to the sign-in, `/metrics` and `/api/v1/me`
  401. No proxy host points at GlitchTip. `/readyz` answers 503 for about two
  minutes after the container is recreated, until the new scheduler takes the
  lock; an uptime monitor should use `/healthz`.
- `ddclient`'s Cloudflare token (`/home/pi/dockers/ddclient/config/ddclient.conf`,
  the `zone=hortal.me` block) works: active, and it sees only the `hortal.me`
  zone. Its value is in single quotes in the file; strip them before use, and
  never print it. Only read with it so far.
- Signed in at `https://checkin.hortal.me` as `roberto` (2026-11-21).
- Outside uptime monitor: Montastic (the owner's existing account; alerts by email
  from `no-reply@email.montastic.com` to the owner's Gmail) watches
  `https://checkin.hortal.me/healthz`, added 2026-11-21. It already watches
  hortal.com, hortal.me, Home Assistant and Jellyfin.
- GlitchTip alerts go to Telegram (2026-11-21): project alert "Telegram" (any issue
  with 1 event in 10 minutes, plus uptime monitors) with a generic-webhook recipient
  `https://api.telegram.org/bot<token>/sendMessage?chat_id=414665210`: the bot and
  chat Home Assistant and the cron set-up use (`rhmhome_bot`, from `config/.env`).
  The token is in GlitchTip's database. Telegram takes the webhook's `text` and
  ignores its `attachments`, so a message only says "GlitchTip Alert" or "GlitchTip
  Uptime Alert": open GlitchTip for the detail. Checked end to end with a test error
  (issue 2 in GlitchTip, still open; resolve it in the UI).
- Fixed the same day: the heartbeat monitor had been created on 2026-11-18 with
  `monitor_type="heartbeat"`; GlitchTip's value is `"Heartbeat"`. Pings were recorded,
  but every scheduled check treated it as a URL monitor with no URL and marked it
  down, so it flapped every minute from 2026-11-18 (unnoticed, no alert existed;
  four Telegram messages went out before it was found). Set to `"Heartbeat"`; steady
  up since 09:43 UTC. Create monitors in GlitchTip's UI, not by hand in the shell.

## Where things stood (2026-11-18, night)

- Phases 0-7 done on the branch: the engine (`eportem/core`), the fake, the
  calendar and templates, settings, the database, the scheduler, auth and API,
  the web UI (English/Spanish) and Docker with GlitchTip. `make check` passes
  (about 555 tests, coverage floor 85% on `eportem/`). Last commit on the
  branch: see `git log -1 origin/refactor/multiuser-service`.
- Phase 8 started: the read-only contract check against the real site passed
  from `omv` (18:50), and the shadow runs on `omv` in dry run next to cron
  (below). Nothing on `omv`'s live checkout or crontab was changed.
- Next, in order: (1) compare the shadow with cron each evening from
  2026-11-19; (2) make `checkin.hortal.me` public (done, see above);
  (3) done: GlitchTip alerts go to Telegram, Montastic watches `/healthz`;
  (4) after about 3 matching working days, the switch (PLAN.md phase 8).
- Open questions for the owner: the region for public holidays (only Spain's
  national ones now); where GlitchTip alerts should go (it has no email);
  whether to use `ddclient`'s Cloudflare token (below); where CI should run
  (D-024: the workflow sits in `.gitea/workflows/` and runs nowhere yet; either
  give the Gitea→GitHub mirror token the `workflow` scope and move it back, or
  enable Gitea Actions with a runner on `omv`).

## Continuing on another machine

- Clone from Gitea (HTTPS works from outside the LAN):
  `git clone https://gitea.tiorob-home.mywire.org/roberto/eportem.git && cd eportem
  && git switch refactor/multiuser-service`. Commit and push to Gitea only.
- `make venv` needs `python3.13` (`brew install python@3.13`, or
  `make venv PYTHON=/path/to/python3.13`), then `make check`. `make test-fast`
  skips the real-browser tests (those need Chrome; Selenium fetches the driver).
- Recreate the untracked `.portability-denylist` at the repository root (it
  makes the portability test catch personal names locally), one per line:
  `omv`, `omve`, `tiorob-home`, `mywire.org`, `wallstreetenglish.com`,
  `hortal.me`.
- Docker Desktop is only needed to build and try the image locally.
- `omv` is `ssh omv` on the home LAN and `ssh omve` from outside (port 61022);
  the new machine needs those SSH aliases and its key authorised for `pi`.
- Personal values never go in tracked files except this file,
  `docs/OPERATIONS.md`, `TODO.md` and `docs/http-api-investigation.md` (all
  skipped by the portability test).

## Shadow on `omv` (since 2026-11-18 evening)

- Worktree `/home/pi/Apps/eportem-refactor` (detached at
  `origin/refactor/multiuser-service`). To update:
  `cd /home/pi/Apps/eportem-refactor && git fetch -q origin && git checkout -q
  --detach origin/refactor/multiuser-service && docker compose -p eportem
  --profile dev up -d --build`. **Not** `--profile errors` any more: GlitchTip
  moved out of this project on 2026-11-21 (below), and that profile would start
  a second, empty GlitchTip here.
- Untracked there: `.env` (`chmod 600`; secrets generated on `omv`;
  `EPORTEM_DRY_RUN=true`; `EPORTEM_TARGET_URL=http://fake-eportem:8081`;
  `EPORTEM_PUBLIC_URL=https://checkin.hortal.me`; `EPORTEM_PUBLISH=127.0.0.1:8095`;
  `EPORTEM_TRUSTED_PROXIES=192.168.32.0/20` (nginx-proxy-manager's network);
  metrics token; GlitchTip DSN and heartbeat URL on `glitchtip:8000`) and
  `docker-compose.override.yml` (joins `ngingx-proxy-manager_default` and the
  `glitchtip` network; previous version `.bak-20261121`).
- Containers: `eportem-eportem-1` (`127.0.0.1:8095`) and
  `eportem-fake-eportem-1`, about 115 MB together.
- GlitchTip is its own stack since 2026-11-21: `/home/pi/dockers/glitchtip`,
  container `glitchtip` (`127.0.0.1:8098`, network `glitchtip`), on the shared
  Postgres (`/home/pi/dockers/postgres`, database `glitchtip`), for every
  service on `omv`. Its data (organisation, project, DSN key, heartbeat monitor,
  the Telegram alert, issues) moved with it, so `.env` didn't change. The old
  volumes `eportem_glitchtip-db` and `eportem_glitchtip-uploads` are kept for
  rollback; delete them after about a week. Details in the homelab repo,
  `hosts/omv/services/glitchtip.md`.
- Logins: the service user `roberto` (admin), password in
  `/home/pi/.eportem-admin-password`; GlitchTip `admin@hortal.me`, password in
  `/home/pi/.glitchtip-admin-password` (both `chmod 600`, 24 random characters).
  GlitchTip has the organisation `eportem`, project `eportem` (DSN in `.env`)
  and a heartbeat monitor "eportem scheduler". To open the UIs from a laptop:
  `ssh -L 8095:127.0.0.1:8095 -L 8098:127.0.0.1:8098 omv` (or `omve`).
- Daily comparison with cron (run in the worktree; exit 0 = every day matches):
  `cat /home/pi/Apps/eportem/logs/actions.log | docker compose -p eportem exec -T
  eportem python -m eportem shadow-report --user roberto --actions-log /dev/stdin
  --days 3`
- To re-import the cron set-up (the container's user can't read `pi`'s
  `chmod 600` files, so stream copies in and delete them after):
  ```
  cd /home/pi/Apps/eportem
  FILES="config/.env config/config.json config/.session_cookies.json $(ls logs/actions.log*)"
  for f in holiday_override.txt location_override.txt business_trip_override.txt; do test -f $f && FILES="$FILES $f"; done
  cd /home/pi/Apps/eportem-refactor
  tar -C /home/pi/Apps/eportem -cf - $FILES | docker compose -p eportem exec -T eportem sh -c "rm -rf /tmp/legacy && mkdir -m 700 /tmp/legacy && tar -x -C /tmp/legacy"
  docker compose -p eportem exec -T eportem python -m eportem import-legacy --user roberto --from /tmp/legacy --dry-run
  docker compose -p eportem exec -T eportem python -m eportem import-legacy --user roberto --from /tmp/legacy
  docker compose -p eportem exec -T eportem rm -rf /tmp/legacy
  ```
- To stop the shadow entirely: `docker compose -p eportem --profile dev
  down` in the worktree (add `-v` to delete its data too; that would also
  delete the old GlitchTip volumes). GlitchTip keeps running.

## Making `checkin.hortal.me` public (as planned on 2026-11-18; now done, see above)

- What was found on 2026-11-18: the `CLOUDFLARE_*_API_TOKEN` variables in the
  work Mac's environment belong to the Wall Street English account (they see
  only work zones, not `hortal.me`): never use them for personal domains. The
  `bw` CLI there is locked and points at the work vault. There is no Cloudflare
  connection in Composio. `hortal.me`'s DNS is on Cloudflare
  (`hope`/`vern.ns.cloudflare.com`); `checkin.hortal.me` has no record yet. The
  `ddclient` container on `omv` probably holds a Cloudflare token for
  `hortal.me`; using it was offered to the owner, not done.
- Steps: (1) a DNS record for `checkin.hortal.me` shaped like the other
  `hortal.me` records that reach `omv`; (2) in nginx-proxy-manager (admin UI on
  `omv` port 82; login needed), a proxy host `checkin.hortal.me` →
  `http://eportem-eportem-1:8080`, with a Let's Encrypt certificate and Force
  SSL; (3) sign in at `https://checkin.hortal.me` as `roberto`; (4) keep
  GlitchTip and `/metrics` off the public proxy; (5) optional: behind Cloudflare
  the per-address sign-in limit sees Cloudflare's addresses (the per-user limit
  still works); trusting `CF-Connecting-IP` from Cloudflare's ranges would fix
  that (D-022).
- Then an outside uptime monitor (done 2026-11-21 with Montastic, see above) on
  `https://checkin.hortal.me/healthz` (GET or HEAD), since GlitchTip on `omv`
  can't notice `omv` itself going down.
