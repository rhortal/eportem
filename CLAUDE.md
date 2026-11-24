# CheckIn: guidance for working on this repository

## Where things are written down

- `README.md`: the project documentation (features, usage, settings, CLI,
  testing, development).
- `docs/OPERATIONS.md`: the live host and its state (cron, Chromium, mail,
  Slack credentials, deploying). Read it when an automated run fails.
- `docs/HANDOFF.md`: where ongoing work stands and how to continue it.
  Update it at the end of each session.
- `docs/refactor/PLAN.md` and `docs/refactor/DECISIONS.md`: the refactor to a
  multi-user service, and the decisions behind it.
- `docs/http-api-investigation.md`: how direct-HTTP clocking was worked out.
- `TODO.md`: open items for the host.

This file only holds general guidance. Host names, paths, accounts and session
state go in the files above, never here.

## Keep README.md current

When a change alters user-visible behaviour (a new script or CLI flag, a
changed file format, a renamed environment variable or setting, a feature added,
removed or moved), update README.md in the same commit, not as a follow-up.

Separately, check README.md for drift at the start of a session if it's
been a while: run `git log -1 --format=%cd -- README.md` and compare
against `git log -10 --oneline`. If meaningful commits have landed since the
last README touch (roughly a couple of weeks, or several feature-shaped
commits, whichever comes first), read README.md against the current state of
the code and fix what's gone stale, even if the user didn't ask.

## Commits and pushes

- Push to `origin` (the maintainer's Gitea) only. Gitea mirrors to GitHub by
  itself; never push to GitHub directly or add it as a remote.
- Run `make check` (lint, tests with coverage, the portability test) before
  every commit, and commit only when it passes.
- Personal or install-specific values (host names, domains, email addresses,
  private IPs, paths on the host) only go in `docs/OPERATIONS.md`,
  `docs/HANDOFF.md`, `TODO.md` and `docs/http-api-investigation.md`. The
  portability test enforces it for every other tracked file, this one
  included. A local, untracked `.portability-denylist` adds personal names to
  the check (see `docs/HANDOFF.md`).

## Testing against ePortem

There is one real ePortem account and it is in live use. Nothing in development
or tests may call the real clock endpoint. Use the fake ePortem
(`fake_eportem/`). The only sanctioned contact with the real site from
development is the read-only contract check (`python -m checkin.contract`),
run on the host at a time no cron line is due.

## Archived experiments: web UI, Docker and mock server (removed 2026-08-10)

`web_ui/`, `Dockerfile`/`docker-compose.yml`, and the mock server
(`utility/server.py`, `mock_server/`, `run_mock_server.py`, plus the tests
that only existed to cover them: `tests/test_api.py`, `tests/test_ui_live.py`,
`tests/conftest.py`, `tests/test_with_mock.py`) were experiments that never
got adopted — the user only ever ran the plain scripts (`run.sh` → `main.py`
→ `eportem_action.py`) via cron. A full-codebase review earlier the same day
found real problems in the web UI (Werkzeug debug mode bound to `0.0.0.0`,
unauthenticated endpoints returning plaintext credentials) and the mock
server (wrong template path, mock login fields that didn't match the real
ePortem login form since the `usuario` rename) — rather than fix unused,
broken code, the user asked to delete it.

Nothing is truly gone: the full pre-removal tree is the tag
`archive/web-ui-docker-mock-server` (the last commit before the removal; it
was a branch until 2026-11-16, when the archive branches became tags). The
tag `archive/holidays-json-experiment` keeps an unmerged July 2026 experiment
with holidays and business trips in a JSON file, superseded by
`holiday_override.py` / `override_location.py`. `eportem_action.py` and
`utility/login_and_navigate.py` also got a cleanup pass to drop the
`USE_MOCK_SERVER`/`--mock`/`--use-mock-server` branches that existed only to
support the mock server — the real automation path's behavior is unchanged
(those branches only ever swallowed errors or diverged when mocking).

If asked to add a web UI, dashboard, or Docker packaging back: this isn't
starting from scratch, there's a whole prior implementation on that archive
branch worth looking at first (with known issues to fix, not copy as-is).

## The multi-user service (`checkin/`)

Replaced cron with a built-in scheduler, and added multiple users, a web UI
and API, and Docker packaging. Built on `refactor/multiuser-service` and
merged into `main` after the cutover (PLAN.md phase 8) went clean; the
service is what clocks now. Update `docs/refactor/PLAN.md` and
`docs/refactor/DECISIONS.md` in the same commit as the code they describe.
The cron scripts at the root stay, working, as the rollback until phase 8
step 6 removes them; don't break them before then. Never hold a database write lock across network I/O
(D-019).
