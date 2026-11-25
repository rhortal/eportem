---
name: checkin
description: Manage the user's CheckIn account, the service that clocks them in and out of ePortem automatically, and clock in, out or to lunch on request. Use when the user asks to clock in or out (fichar), go on or come back from a break, about their clocking (fichajes), their current status, today's or next week's plan, days off, holidays or vacations, working from home or the office on some day, business trips, different hours on a day, pausing CheckIn, their working-day schedule, notifications, or whether a clock-in or clock-out went through. Signs in through a link the user approves; never asks for a password.
---

# CheckIn

CheckIn clocks the user in and out of ePortem on their schedule. This skill reads
and changes their CheckIn account through its API with `scripts/checkin.py`
(Python 3, standard library only). Run it with the path of this skill's folder:

```bash
python3 <this skill's folder>/scripts/checkin.py status
```

Every command prints JSON. Exit codes: 0 fine, 1 the request failed (the error says
why), 2 bad usage, 3 not signed in, 4 still waiting for the user to approve.

## Signing in

Never ask for the user's CheckIn or ePortem password, and never print, log or
repeat the token: the script keeps it in `~/.config/checkin/agent.json` itself.

1. `checkin.py login` prints `open_this_link` and `code`. Give the user both and ask
   them to open the link, check that the page shows the same code, and approve.
   (If the skill doesn't know the address of the user's CheckIn, ask them for it and
   run `login --url https://...`. Add `--read-only` if the user only wants you to look.)
2. Run `checkin.py login --wait`. It waits up to about 100 seconds; exit code 4
   means not approved yet: run it again (the code lives 10 minutes).
3. Exit code 3 on any command later means the token expired (after 90 days) or was
   revoked: sign in again the same way.

`checkin.py logout` revokes this agent's token. `checkin.py whoami` says where and as
whom you are signed in, without calling the server.

## Reading

- `state`: what ePortem shows right now (see below).
- `status`: who, today's plan (`today`: works, reason, location, planned times),
  today's runs and their status, the next run, and the setup checklist. Start here.
- `get /calendar from=YYYY-MM-DD days=14` (1 to 62 days): what will happen each day
  and why (`reason`: workday, weekend, public holiday, time off...), home or office.
- `get /runs from=YYYY-MM-DD to=YYYY-MM-DD`: clock events and their status
  (`recorded` went through; `failed`, `not_recorded` or `unknown` need a look);
  `get /runs/ID/log` for the log of one.
- `get /days` (changes to single days), `get /schedule`, `get /templates`,
  `get /periods`, `get /local-holidays`, `get /channels`, `get /me`, `get /tokens`.

## Changing things

Say what you are about to change before you do it, in a sentence, and report what
the server answered. Dates are `YYYY-MM-DD`; times `H:MM`, local to the user.

- **Days off, home or office, trips, other hours**: `post /days '{...}'` with `kind`:
  - `time_off`: no clocking (holiday, sick day). `{"kind": "time_off", "start_date":
    "2026-12-24", "end_date": "2026-12-31", "note": "Christmas"}`
  - `location`: work from `home` or the `office` on those days, instead of the usual
    pattern. `{"kind": "location", "start_date": "2026-12-02", "location": "home"}`
  - `business_trip`: away on a trip. Working days are still clocked, with `location`
    (`home` or `office`) as the place recorded. Use `time_off` instead if the user
    should not be clocked at all.
  - `times`: other hours on those days. `"times": {"start": "8:00", "stop": "15:00"}`
    (add `"lunch_out"` and `"lunch_back"` for a lunch break).
  - `work_on_holiday`: clock on a public holiday as on a normal day.
  `end_date` defaults to `start_date`. A later change wins over an earlier one. Undo
  with `delete /days/ID` (the id from `get /days`).
- **Pause or resume everything**: `patch /me '{"paused": true}'` (or `false`).
- **The usual week**: `put /schedule '{...}'` with any of `template_key` (one of
  `get /templates`), `location_weeks` (`[{"0": "office", ..., "4": "home"}]`, weekday
  0 is Monday; two weeks plus `pattern_anchor` to alternate), `holiday_country`,
  `holiday_region` (e.g. `ES`, `MD`).
- **Another template for a date range** (summer hours): `post /periods
  '{"template_key": "...", "start_date": "...", "end_date": "...", "label": "Summer"}'`.
- **A local holiday**: `post /local-holidays '{"date": "...", "name": "..."}'`.
- **Random offset**: `patch /me '{"jitter_before_minutes": 5, "jitter_after_minutes": 4}'`.

The server checks every change and answers 422 with the problems; fix them and try
again rather than guessing.

## Clocking in and out now, as in ePortem

The user can clock and change status through you, as they would by pressing the
buttons in ePortem: start the day, go on the lunch break, come back, stop.

1. `checkin.py state` reads ePortem's dashboard right now (it never clocks): `state`
   is `working`, `on_break` or `not_working`, and `available_actions` lists what can
   be sent from there (`start_day` and `after_lunch` with `home` or `office`,
   `lunch_break`, `stop_day`). Use it to turn "clock me in", "I'm off to lunch",
   "I'm back" or "I'm done for today" into the action, and to spot a request that
   doesn't fit (clocking in while already working).
2. Say exactly what you will send, e.g. "Clock in now, from home?", and wait for the
   user's yes. A clock event is real and can't be undone from here; an explicit
   request in their message ("clock me in from home now") counts as the yes.
3. `checkin.py clock ACTION [--location home|office] --yes` sends it now, outside the
   schedule, and waits for ePortem's answer: `recorded: true` means it went through.
   Otherwise report `status`, `error` and the end of `log`. Location defaults to
   the day's plan.

Each action can be clocked once a day: if today's run already went through, the
server answers 409. A manual clock replaces that day's planned run for the same
action, so the scheduler won't send it again. Never clock to "fix" or "test" something
the user didn't ask for. Statuses other than these four (other pauses such as an
absence or a medical appointment) aren't supported: tell the user to use ePortem
for those.

## Never

- Change the ePortem account (`/eportem-account`), passwords, tokens or other users,
  unless the user asks for exactly that.
- Send notification tests or create channels with secrets the user didn't give you.

## Anything else

The whole API is described at `<app address>/api/docs`;
`checkin.py get|post|put|patch|delete PATH [JSON] [key=value...]` reaches any of it
(a JSON body of `-` reads it from stdin).

## Updates

The script notes on stderr, at most once a day, when a newer version of this skill
is out. Tell the user; `checkin.py update` installs it (it checks the download's
checksum), and `update --check` only looks.
