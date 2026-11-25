# Handoff

Where the work stands and how to pick it up, for the next session or another
machine. This file holds host-specific details (host names, paths, logins), so
the portability test skips it, like `docs/OPERATIONS.md` and `TODO.md`. Update it at the
end of each session. General guidance lives in `CLAUDE.md`, the live host in
`docs/OPERATIONS.md`, the plan in
`docs/refactor/PLAN.md`, the decisions in `docs/refactor/DECISIONS.md`.

## Start here (2026-11-25, personal laptop): the site is live

The hosting runbook below is **done** (all 8 steps, 08:30-09:40):
- `https://checkin.hortal.me` is this website on **Cloudflare Pages**: project `checkin` on the
  owner's personal account (`checkin.pages.dev` was taken globally, so its address is
  `checkin-api.pages.dev`; the `checkin` CNAME, proxied, points there). Deploy:
  `python3 website/build.py && wrangler pages deploy website/dist --project-name checkin --branch main`
  (check `wrangler whoami` first: the personal account, never the work one).
- The app is `https://checkin-app.hortal.me` (proxy host 74, `CHECKIN_PUBLIC_URL` changed,
  Montastic moved; see `main`'s `docs/OPERATIONS.md`). Proxy host 73 and cert 93 deleted.
- `website/site.env` (untracked) on the personal laptop: `SITE_URL=https://checkin.hortal.me`,
  the owner's name, `CONTACT_EMAIL=checkin@hortal.me`, `HOSTING_PROVIDER=Cloudflare`.
- Contact: `checkin@hortal.me` is a Mailu **mailbox** (password in Bitwarden
  "mail.hortal.me (checkin@hortal.me)"). A forward-only alias doesn't work: SMTP2GO, Mailu's
  outgoing relay, refuses forwarded mail from unverified domains (and the bounce is lost). The
  owner plans an n8n "re-send as the mailbox" workflow; recipe in the homelab repo,
  `hosts/omv/services/mailu.md`. A test from outside arrived in the mailbox.
- Analytics (owner's request): Cloudflare Web Analytics, turned on in the Pages project; the
  privacy page and footer say so (`e792e49`), and the privacy page now names the host and says we
  keep no access logs (`LOG_RETENTION_DAYS` gone).

Follow-ups, not done:
- **Two beacons on the page**: the Pages project's Web Analytics *and* the `hortal.me` zone's
  automatic install both inject `beacon.min.js` (seen in headless Chrome), so each visit is counted
  in two Web Analytics sites. Keep one: turn off the Pages toggle, or exclude `checkin.hortal.me`
  from the zone's automatic install (a Web Analytics rule; zone-wide setting, ask first).
- Done 2026-11-25: `404.html` in each language, and root-absolute, extensionless links and
  canonicals (Pages used to redirect every `.html` link).

## Start here (end of the 2026-11-24 session on the work Mac, about 16:15)

Sequence agreed with the owner: the work Mac finishes today's hand-over on
`refactor/multiuser-service` (watch the 18:03 clock-out and the day check, then the
merge to `main` at 18:44); **after that**, the move to the new hostnames is done from
the other laptop (runbook below), because the work Mac's Cloudflare credentials belong
to the employer. State at hand-over:

- **CheckIn clocks for real on `omv` since 09:30 today** (switch below); cron no longer
  clocks. Today, all at home: start 09:02 (cron, before the switch), lunch 13:32 and
  back 14:28 (CheckIn, over HTTP, no errors), stop planned for **18:03**, then
  CheckIn's own day check about 18:43.
- **D-026 is live** (`4c76e63`, deployed 15:13): the clock-in only ever before the
  template's start, the clock-out only ever after its stop (08:51-08:59:30 and
  18:00:30-18:09 with the defaults). Templates still say 9:00 and 18:00.
- **Branches:**
  - `refactor/multiuser-service` at `95e7be0` (plus this handoff): what `omv` runs
    (worktree detached at `4c76e63`; the commits since are docs only).
  - `website` (from `95e7be0`): the public site (`69d04a4`) plus this handoff.
    Pushed, not merged anywhere.
  - `main`: still the cron code; not yet fast-forwarded (see "After the switch").
- **A one-shot job is scheduled in the work Mac's Claude session for 18:44 today**
  (session-only: it runs only if that session is still open; the owner wants it to run). It checks the day and,
  if clean, fast-forwards `main` to `refactor/multiuser-service`, pushes, and points
  `omv`'s worktree at `origin/main`. To see whether it ran: `git log origin/main -1`
  (it would equal the branch) and `git -C /home/pi/Apps/eportem-refactor log -1` on
  `omv`. If it didn't run and the day was clean, do those steps by hand (commands in
  "After the switch", step 2). Never do the restart between 17:45 and 18:15 on a
  working day.
- **In progress, nothing changed yet: the move to two hostnames** (next section).
  Only reads were done: the proxy host's files on `omv` and `wrangler whoami` here.

## Hosting plan agreed 2026-11-24: site on Cloudflare Pages, app on its own hostname

Agreed with the owner: the public website takes `https://checkin.hortal.me/` (what's
already on cards and in Montastic), served by **Cloudflare Pages**; the app moves to
**`https://checkin-app.hortal.me`** on `omv`. Why that name: Cloudflare's free
Universal SSL covers only one level below the zone (`*.hortal.me`), so
`app.checkin.hortal.me` would get no edge certificate while proxied (it would need
Advanced Certificate Manager, paid). A `/app` sub-path was rejected: `CHECKIN_ROOT_PATH`
exists but has never run in production, and the site and app would share an origin
and cookies. If CheckIn gets its own domain later: `<domain>` for the site,
`app.<domain>` for the app.

Found while starting (2026-11-24 ~16:10), none of it acted on:
- **The work Mac is the wrong place for Cloudflare.** `wrangler` there is signed in
  (OAuth, `~/Library/Preferences/.wrangler/config/default.toml`) to the **Wall Street
  English** account, and the shell has work tokens `CLOUDFLARE_DOMAINS_API_TOKEN`,
  `CLOUDFLARE_REDIRECTS_API_TOKEN`, `CLOUDFLARE_ZERO_TRUST_ACCESS_API_TOKEN`,
  `CLOUDFLARE_PAGES_API_TOKEN`. Never use any of them for `hortal.me`. On the other
  laptop, check `wrangler whoami` shows the owner's personal account (the one with
  the `hortal.me` zone) before any deploy.
- `ddclient`'s token on `omv` (`/home/pi/dockers/ddclient/config/ddclient.conf`, the
  `zone=hortal.me` block, value in single quotes) can edit `hortal.me` DNS; it can't
  create Pages projects (zone-scoped). Never print it.
- nginx-proxy-manager: container `proxymanager`, compose in
  `/home/pi/dockers/ngingx-proxy-manager` (sic), data in its `/data`
  (`database.sqlite`, `nginx/proxy_host/73.conf`, `letsencrypt-acme-challenge`).
  Host 73 is `checkin.hortal.me` -> `http://checkin-checkin-1:8080`, Let's Encrypt,
  Force SSL. The container has no `sqlite3` binary. Creating a host with a new
  certificate is easiest in its admin UI (port 82 on `omv`; login needed); editing
  the database by hand can't issue a certificate.

### Runbook (the order matters: the app moves first, then the name goes to Pages)

Do the app steps outside the clock windows (not 08:45-09:15, 13:15-13:45,
14:15-14:45, 17:45-18:15 on working days). After a restart the scheduler takes the
lock about 2 minutes later.

1. **DNS for the app**: in Cloudflare (owner's account, zone `hortal.me`), a CNAME
   `checkin-app` -> `hortal.me`, proxied, shaped like `checkin` (which is a proxied
   CNAME to `hortal.me`).
2. **Proxy host** in nginx-proxy-manager: `checkin-app.hortal.me` ->
   `http://checkin-checkin-1:8080`, Websockets on, Let's Encrypt certificate, Force SSL,
   same options as host 73. Keep host 73 for now, so nothing breaks before step 7.
3. **The app's own address**: on `omv`, `cd /home/pi/Apps/eportem-refactor`, back up
   `.env` (`cp -p .env .env.bak-YYYYMMDD-hostname`), set
   `CHECKIN_PUBLIC_URL=https://checkin-app.hortal.me`, then
   `docker compose -p checkin up -d` (add `--build` only if the code moved). Check
   `curl -s https://checkin-app.hortal.me/healthz` and `/readyz`, sign in at
   `https://checkin-app.hortal.me/login` as `roberto` (password in
   `/home/pi/.eportem-admin-password`), and today's runs on the Today page.
   `CHECKIN_TRUSTED_PROXIES` is unchanged (same proxy).
4. **Montastic**: change the `/healthz` monitor to `https://checkin-app.hortal.me/healthz`.
   Optionally add one for `https://checkin.hortal.me/` once the site is up.
5. **A contact address that reaches the owner** (do this before publishing the site,
   since every page shows it). Found 2026-11-24, nothing changed: mail for `hortal.me`
   is handled by **Mailu on `omv`** (`/home/pi/dockers/mailu`, `DOMAIN=hortal.me`,
   `HOSTNAMES=mail.hortal.me`, outgoing via the relay `mail-eu.smtp2go.com:587`). Public
   DNS: MX `hortal.me` -> `mail.hortal.me` (the home IP, not proxied); SPF
   `v=spf1 mx a:mail.hortal.me ~all`. The work Mac's DNS returns a LAN address for both
   (a local override), so check records with `dig @1.1.1.1`. Mailu already has
   forward-only aliases to the owner's Gmail (e.g. `contact@baldinnovator.com`), and an
   unrelated mailbox `eportem@hortal.me` (don't reuse it; its purpose is unknown).
   Don't turn on Cloudflare Email Routing for `hortal.me`: it replaces the MX records and
   would cut Mailu off.
   - Pick the address with the owner (e.g. `checkin@hortal.me` or `hola@hortal.me`).
   - Mailu admin (`https://mail.hortal.me/admin`, login needed) -> Aliases -> add it
     with destination the owner's Gmail, like the existing aliases. CLI alternative:
     `docker exec mailu-admin-1 flask mailu alias hortal.me <local-part> <destination>`.
   - Test from outside: send to the new address from a different provider (not from
     the same Gmail, which can hide its own forwarded copy), check it arrives in the
     inbox, not spam, and that the headers show SPF pass; send a second test with a
     link to see that forwarding doesn't break.
   - Replying as that address (optional): Gmail -> Settings -> Accounts -> "Send mail
     as", using an SMTP login for it (a Mailu mailbox instead of an alias, or the SMTP2GO
     relay); otherwise replies go out from the Gmail address.
   - Put it in `website/site.env` as `CONTACT_EMAIL`, and in the privacy page's
     wording if the step-6 rewording mentions mail.
6. **The site**: on the branch `website`, create `website/site.env` (untracked; see
   `website/site.env.example`) with `SITE_URL=https://checkin.hortal.me`, the owner's
   name, the contact email from step 5, and
   `NETWORK_PROVIDER=Cloudflare`. **First reword the privacy page's server-log bullet**:
   it promises our server deletes access logs after `LOG_RETENTION_DAYS` days, but on
   Pages we keep no logs and Cloudflare is the host. `python3 website/build.py`, look at
   `website/dist/`, then `wrangler pages project create checkin` (owner's account) and
   `wrangler pages deploy website/dist --project-name checkin`. Pages can't connect to
   Gitea, so deploys are direct uploads of the built folder.
7. **The name goes to Pages**: in the Pages project, add the custom domain
   `checkin.hortal.me`. Cloudflare then wants the `checkin` record to be a CNAME to
   `checkin.pages.dev` (it offers to change it, since the zone is in the same account).
   From then on `checkin.hortal.me` is the site. Delete proxy host 73 in
   nginx-proxy-manager (its certificate can go too).
8. **Afterwards**: update `docs/OPERATIONS.md` (hostnames, Montastic, Pages, the
   contact alias), this
   file, and the GlitchTip/Telegram notes if any link names the old host. Links the
   app sends (emails, alerts) come from `CHECKIN_PUBLIC_URL`, so they follow step 3.

Rollback: until step 7, `checkin.hortal.me` still reaches the app; restoring the
`.env` backup and `up -d` undoes step 3. After step 7, set the `checkin` record back
to a proxied CNAME to `hortal.me` and re-enable host 73.

## Switched to CheckIn (2026-11-24, 09:20-09:30)

CheckIn on `omv` now clocks for real; cron no longer does (PLAN.md phase 8, step 3).
- Rehearsal first: a throwaway Compose project with the dry run off against the
  fake (own database, port 8197, no channels). Verify logged in by browser, then
  `start_day` over HTTP, then after expiring the fake's session `lunch_break` logged
  in again and clocked; the fake saw exactly one event each. Removed with `down -v`.
- Crontab: backup `/home/pi/crontab.bak-20261124-switch`. The six clocking lines and
  the 18:40 `--verify-day` line are commented out with the prefix
  `#SWITCHED-TO-CHECKIN-20261124`; the home one-shot lines for today were removed
  (they had already run at 00:05).
- Worktree moved to `05f8848` (docs only since `625d8b0`, same image). `import-legacy`
  run again from the cron checkout: fresh session cookies (cron's 09:02 login) and
  today's `start_day` stored as recorded (`legacy-http`), so it isn't repeated.
- `.env`: `CHECKIN_DRY_RUN=false`, `CHECKIN_TARGET_URL` removed (default
  `https://eportem.es`); backup `.env.bak-20261124-switch`. Recreated with
  `docker compose -p checkin up -d` (no `--profile dev` from now on); the fake
  container removed. Ready at once; `config show` confirms both settings.
- Today as planned by the service, all home: lunch_break 13:31, after_lunch 14:27,
  stop_day 17:55 (local), then its own day check 40 minutes after the last action.
  Telegram and Slack channels are on (imported from `config/.env`).
- To update from now on: `git fetch -q origin && git checkout -q --detach
  origin/refactor/multiuser-service && docker compose -p checkin up -d --build`
  (no `--profile dev`).
- **Rollback** (step 5): `docker compose -p checkin stop` in the worktree, then
  `crontab /home/pi/crontab.bak-20261124-switch` (its one-shot line is date-guarded,
  harmless). The cron checkout and `config/.env` are unchanged. Note the service
  holds the newer session cookies only if it had to log in; cron logs in by itself
  when its own cookies expire.
- Next: watch the first full day (step 4): each run on the runs page or `/runs`,
  the day check, Telegram/Slack messages. Then two clean weeks before step 6
  (delete `legacy/` and the cron docs). The shadow-report command no longer applies.

## Public website: branch `website` (started 2026-11-24)

What exists (commit `69d04a4`, decision D-027, details in `website/README.md`):
- `website/src/`: `index`, `terms`, `privacy`, `legal` in English (`/`) and Spanish
  (`/es/`), same file names; partials `_header`, `_footer`, `_logo` and one per
  picture (`_v-*.{en,es}.html`); `assets/site.css` (the product's palette) and
  `assets/favicon.svg`.
- `website/build.py` (standard library): fills `{{KEY}}` placeholders from the untracked
  `website/site.env`, resolves `<!--include:...-->` and `<!--if:KEY-->` blocks, writes
  `website/dist/` (gitignored). Fails on a missing value or include.
  `--example` builds a preview from `site.env.example` (made-up "Alex Example").
- `tests/test_website.py`: both languages for every page, nothing left unfilled, the
  ePortem disclaimer on every page, nothing loaded from other sites, internal links
  resolve, every picture catalogued in `VISUALS.md`, build failures. The portability
  test now allows `www.aepd.es`.
- Content decided with the owner: no sign-up (placeholder; "ask about early access"
  is a mailto); terms say CheckIn isn't responsible for wrong, late, missing or
  duplicate clock events, the user stays responsible for their *registro de jornada*,
  must only record time they work and follow their employer's rules; Spanish law,
  consumers keep their own courts; the Spanish text of the terms prevails. Trademark
  disclaimer on every page. No screenshots of ePortem: the only picture of a
  time-recording site is a generic drawing labelled as an illustration.
- The owner asked that every picture's source be recorded for the coming UI redesign:
  `website/VISUALS.md` plus a comment at the top of each `_v-*.html`. Gaps it found in
  the product: the English UI shows raw action keys (`start_day`...); notifications
  are English-only (the `TODO.md` multilingual item).
- Checked by eye at 1280 px and on an emulated 390 px phone (no horizontal overflow)
  with headless Chrome; dark mode follows the system.

Open, for the owner:
- The contact address to publish (runbook step 5), and the name as it should appear.
- A legal review of the terms and privacy policy before the service takes users.
- The privacy page's server-log bullet must be reworded for Cloudflare Pages
  (runbook step 6). `LOG_RETENTION_DAYS` is required by the build today; make it
  optional or drop it when rewording.
- Merge `website` into the main line when it's published (no conflicts expected:
  it only adds files, plus README, D-027, `.gitignore`, the portability allowance and
  this file).

## After the switch: agreed with the owner (2026-11-24)

- 15:13: D-026 deployed (`4c76e63`): the clock-in only before the start time, the
  clock-out only after the stop time. On start-up the service moved today's
  stop_day from 17:55 to 18:03 (the new scheduler takes the lock about 2 minutes
  after a restart, so re-planning shows up then, not at once). Lunch 13:32 and back
  14:28 were clocked over HTTP before that.

1. Today: check the 13:31 run, then the whole day after the service's day check
   (about 18:35).
2. If the day is clean: fast-forward `main` to `refactor/multiuser-service` (no
   conflicts: `main` has nothing the branch lacks), push, and point the worktree on
   `omv` at `main` instead of the branch. The branch keeps `run.sh` and the cron
   path at the root, so the cron checkout (the rollback) still works after a pull.
3. About 2026-11-28 (approved): delete the volumes `eportem_eportem-data`,
   `eportem_glitchtip-db`, `eportem_glitchtip-uploads`, and on the homelab side
   `Dockerdata/paperless/db.MOVED-TO-SSD-20261121`.
4. About 2026-12-08, after two clean weeks (PLAN.md phase 8, step 6): delete the
   cron scripts and their docs, rewrite the operations sections of README and
   `docs/OPERATIONS.md`; on `omv` remove the cron checkout, the commented crontab
   lines and their backup, the `.env` and crontab `.bak` files, and consider a
   tidier home for the service than `/home/pi/Apps/eportem-refactor`.

## Home on Tuesday 2026-11-24 (set 2026-11-23; done)

- The owner works from home on 2026-11-24 (a normal office day), and plans the
  switch that morning before 9:00. Both systems know:
  - Service: a day change (`kind: location`, home, 2026-11-24, id 1) added through
    the API with a one-off token (revoked); `resolve()` gives home, "changed for
    this day". Runs for the day are planned at midnight.
  - Cron: `location_override.txt` only works for the current day, so `pi`'s crontab
    has a date-guarded line at 00:05 on 2026-11-24 running
    `override_location.py home` (marker `#eportem-home-oneshot-20261124`, log
    `logs/home-oneshot-20261124.log`; crontab backup
    `/home/pi/crontab.bak-20261123-home-oneshot`). Remove those two lines after the day
    (or at the switch, when the clocking lines are commented out).

## Shadow verdict (2026-11-23)

- `shadow-report --days 6` exits 0 at 18:08: 2026-11-19, 2026-11-20 and 2026-11-23
  all match cron on every action, location and minute (today: 08:56/08:55,
  13:33/13:28, 14:30/14:33, 17:59/17:59, office). `omv` rebooted early on
  2026-11-22 (weekly) and the service came back by itself. Ready for the switch
  (PLAN.md phase 8, steps 3-5), at a quiet time chosen by the owner.
- Same day, homelab: the cloud-drives backup (watched by the new heartbeats) had
  been failing, probably since 2026-09-24: nginx-proxy-manager's probe rule
  403'd `.git` folders over Nextcloud WebDAV, and Google Drive had dangling
  shortcuts. Both fixed; a manual run copied everything with 0 errors.

## Where things stand (2026-11-21, end of session)

- Shadow on `omv` healthy as Compose project `checkin` (dry run, fake target):
  2026-11-19 and 2026-11-20 match cron; `https://checkin.hortal.me` shows CheckIn.
- Pre-switch checklist in PLAN.md phase 8 is complete except the shadow report:
  public hostname, Telegram alerts from GlitchTip, Montastic on `/healthz`, and
  the owner signed in. GlitchTip is now the host's own stack (homelab repo,
  `hosts/omv/services/glitchtip.md`), on a shared Postgres.
- Next, in order: (1) Monday 2026-11-23 evening, the shadow report (command in
  "Shadow on `omv`" below; now `-p checkin`); if it matches, (2) the switch
  (PLAN.md phase 8, steps 3-5) at a quiet time. Before switching, consider a
  rehearsal with the dry run off against the fake (a separate throwaway stack),
  since the shadow never exercises the send.
- Open questions for the owner: the region for public holidays; CI (a Gitea
  Actions runner already exists on `debian`, see below); the multilingual item
  in `TODO.md`.
- Clean-ups due about 2026-11-28, with the owner's OK: the volumes
  `eportem_eportem-data`, `eportem_glitchtip-db`, `eportem_glitchtip-uploads`;
  on the homelab side `Dockerdata/paperless/db.MOVED-TO-SSD-20261121`.

## Renamed to CheckIn (2026-11-21)

- The project is CheckIn (D-025); "ePortem" stays only where it names the site.
  The shadow was moved over the same day: old project stopped
  (`docker compose -p eportem --profile dev down`), worktree on the rename commit,
  `.env` lines `EPORTEM_*` renamed to `CHECKIN_*` (backup
  `.env.bak-20261121-rename`, also `docker-compose.override.yml.bak-20261121-rename`),
  new project `checkin` created, the old volume's data copied into
  `checkin_checkin-data` with `eportem.db*` renamed to `checkin.db*`, then started.
  Checked: healthy, dry run, `checkin.db`, the public site shows CheckIn,
  `shadow-report` OK for every day, heartbeat pings arriving, no old-name warnings.
- nginx-proxy-manager's host 73 now forwards to `checkin-checkin-1` (changed in its
  SQLite database and in `73.conf`, then `nginx -t` and a reload; backups
  `database.sqlite.bak-20261121-checkin` in its data folder and
  `/home/pi/npm-proxy_host-73.conf.bak-20261121`).
- GlitchTip display names renamed (organisation "CheckIn", project "checkin",
  monitor "checkin scheduler"); slugs unchanged, so the DSN and heartbeat URL are
  the same.
- Rollback copies to delete after about a week: the volume `eportem_eportem-data`
  (with `eportem_glitchtip-db`, `eportem_glitchtip-uploads`).
- Not renamed: the Gitea/GitHub repository, the worktree path
  `/home/pi/Apps/eportem-refactor`, the live cron checkout `/home/pi/Apps/eportem`
  and `main`.

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
- The service logs JSON to `docker logs checkin-checkin-1`;
  `docker logs --since` returned nothing for it on 2026-11-21, so read the
  whole log and filter.

## Public hostname: done (found 2026-11-21)

- `checkin.hortal.me` already had a proxied CNAME to `hortal.me` in Cloudflare
  and an nginx-proxy-manager host (`proxymanager`, `proxy_host/73.conf`) to
  `http://checkin-checkin-1:8080` (was `eportem-eportem-1` until the rename) with a Let's Encrypt certificate and Force
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

- Phases 0-7 done on the branch: the engine (`checkin/core`), the fake, the
  calendar and templates, settings, the database, the scheduler, auth and API,
  the web UI (English/Spanish) and Docker with GlitchTip. `make check` passes
  (about 555 tests, coverage floor 85% on `checkin/`). Last commit on the
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
  enable Gitea Actions with a runner on `omv`). Found 2026-11-21: a runner
  already exists, container `gitea-runner` (`gitea/act_runner:0.6`) on `debian` next to
  Gitea; check whether it's registered and Actions are on, then `.gitea/workflows/check.yml`
  could run there).

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
  --detach origin/refactor/multiuser-service && docker compose -p checkin
  --profile dev up -d --build`. **Not** `--profile errors` any more: GlitchTip
  moved out of this project on 2026-11-21 (below), and that profile would start
  a second, empty GlitchTip here.
- Untracked there: `.env` (`chmod 600`; secrets generated on `omv`;
  `CHECKIN_DRY_RUN=true`; `CHECKIN_TARGET_URL=http://fake-eportem:8081`;
  `CHECKIN_PUBLIC_URL=https://checkin.hortal.me`; `CHECKIN_PUBLISH=127.0.0.1:8095`;
  `CHECKIN_TRUSTED_PROXIES=192.168.32.0/20` (nginx-proxy-manager's network);
  metrics token; GlitchTip DSN and heartbeat URL on `glitchtip:8000`) and
  `docker-compose.override.yml` (joins `ngingx-proxy-manager_default` and the
  `glitchtip` network; previous version `.bak-20261121`).
- Containers: `checkin-checkin-1` (`127.0.0.1:8095`) and
  `checkin-fake-eportem-1`, about 115 MB together. Compose project `checkin`,
  data volume `checkin_checkin-data` (database `checkin.db`).
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
  GlitchTip has the organisation "CheckIn" (slug `eportem`, which is in the
  heartbeat URL), project "checkin" (slug `eportem`, id 1; DSN in `.env`) and a
  heartbeat monitor "checkin scheduler". To open the UIs from a laptop:
  `ssh -L 8095:127.0.0.1:8095 -L 8098:127.0.0.1:8098 omv` (or `omve`).
- Daily comparison with cron (run in the worktree; exit 0 = every day matches):
  `cat /home/pi/Apps/eportem/logs/actions.log | docker compose -p checkin exec -T
  checkin python -m checkin shadow-report --user roberto --actions-log /dev/stdin
  --days 3`
- To re-import the cron set-up (the container's user can't read `pi`'s
  `chmod 600` files, so stream copies in and delete them after):
  ```
  cd /home/pi/Apps/eportem
  FILES="config/.env config/config.json config/.session_cookies.json $(ls logs/actions.log*)"
  for f in holiday_override.txt location_override.txt business_trip_override.txt; do test -f $f && FILES="$FILES $f"; done
  cd /home/pi/Apps/eportem-refactor
  tar -C /home/pi/Apps/eportem -cf - $FILES | docker compose -p checkin exec -T checkin sh -c "rm -rf /tmp/legacy && mkdir -m 700 /tmp/legacy && tar -x -C /tmp/legacy"
  docker compose -p checkin exec -T checkin python -m checkin import-legacy --user roberto --from /tmp/legacy --dry-run
  docker compose -p checkin exec -T checkin python -m checkin import-legacy --user roberto --from /tmp/legacy
  docker compose -p checkin exec -T checkin rm -rf /tmp/legacy
  ```
- To stop the shadow entirely: `docker compose -p checkin --profile dev
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
  `http://checkin-checkin-1:8080`, with a Let's Encrypt certificate and Force
  SSL; (3) sign in at `https://checkin.hortal.me` as `roberto`; (4) keep
  GlitchTip and `/metrics` off the public proxy; (5) optional: behind Cloudflare
  the per-address sign-in limit sees Cloudflare's addresses (the per-user limit
  still works); trusting `CF-Connecting-IP` from Cloudflare's ranges would fix
  that (D-022).
- Then an outside uptime monitor (done 2026-11-21 with Montastic, see above) on
  `https://checkin.hortal.me/healthz` (GET or HEAD), since GlitchTip on `omv`
  can't notice `omv` itself going down.
