#!/bin/bash
# Clock an action over HTTP (utility/http_clock.py), falling back to the usual
# Selenium run (run.sh -> main.py) only when the HTTP attempt recorded nothing.
#
#   run_http.sh ACTION [LOCATION]      e.g. run_http.sh lunch_break office
#
# Exit codes from http_clock decide the fallback:
#   0  recorded                      -> done
#   3  nothing recorded              -> fall back to run.sh (main.py re-checks the
#                                       schedule, holidays and location)
#   4  outcome unknown               -> no fallback (could clock twice); fail so
#                                       cron mails the output
#   5  recorded, notifications failed -> no fallback; fail so cron mails it
# Anything else (e.g. a Python crash before the request) counts as not recorded only
# if http_clock didn't print "Sending", i.e. never reached the request.

cd "$(dirname "$0")"

ACTION="$1"
LOCATION="${2:-office}"
if [ -z "$ACTION" ]; then
  echo "usage: $0 ACTION [LOCATION]" >&2
  exit 2
fi

# A missing or broken venv: skip HTTP, run.sh rebuilds it and clocks with the browser.
if [ ! -d "venv" ] || ! venv/bin/python3 -c "import selenium, requests, dotenv" &> /dev/null; then
  echo "venv missing or broken; using run.sh"
  exec ./run.sh
fi

out=$(venv/bin/python3 -m utility.http_clock "$ACTION" --location "$LOCATION" --send --notify 2>&1)
rc=$?
echo "$out"

case $rc in
  0) exit 0 ;;
  3) ;;
  4|5) exit 1 ;;
  *)
    if grep -q '^Sending ' <<< "$out"; then
      echo "HTTP clock crashed after sending; not falling back. Check ePortem by hand."
      exit 1
    fi
    ;;
esac

echo "HTTP clock didn't record anything (exit $rc); falling back to the browser (run.sh)"
exec ./run.sh
