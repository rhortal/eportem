#!/bin/sh
# Build the public website and deploy it to Cloudflare Pages, with the token in
# website/deploy.env and nothing else.
#
#   cp website/deploy.env.example website/deploy.env && chmod 600 website/deploy.env
#   # fill in CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN, then:
#   website/deploy.sh            # build, check the account, deploy
#   website/deploy.sh --check    # only check that the token reaches the account and project
#
# wrangler runs with an empty environment and a throwaway home folder, so other
# Cloudflare credentials on the machine (CLOUDFLARE_* variables, a `wrangler login`
# session for another account) can't be picked up by mistake. It deploys only after
# the token is shown to reach CLOUDFLARE_ACCOUNT_ID and its Pages project.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="$HERE/deploy.env"
CHECK_ONLY=no
[ "${1:-}" = "--check" ] && CHECK_ONLY=yes

[ -f "$ENV_FILE" ] || { echo "No $ENV_FILE: copy deploy.env.example to it and fill it in." >&2; exit 2; }
case "$(ls -l "$ENV_FILE" | cut -c5-10)" in
  ------) ;;
  *) echo "$ENV_FILE is readable by others: run chmod 600 on it." >&2; exit 2 ;;
esac

value() {  # KEY=value lines only; the file is never run as a script
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | tr -d "\"' \r"
}
ACCOUNT=$(value CLOUDFLARE_ACCOUNT_ID)
TOKEN=$(value CLOUDFLARE_API_TOKEN)
PROJECT=$(value PAGES_PROJECT)
PROJECT=${PROJECT:-checkin}
[ -n "$ACCOUNT" ] && [ -n "$TOKEN" ] || { echo "Fill in CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in $ENV_FILE." >&2; exit 2; }

WRANGLER=$(command -v wrangler || true)
[ -n "$WRANGLER" ] || { echo "wrangler is not installed (brew install cloudflare-wrangler, or npm i -g wrangler)." >&2; exit 2; }
NODE_DIR=$(dirname "$(command -v node)")

ISOLATED=$(mktemp -d)
trap 'rm -rf "$ISOLATED"' EXIT
cf() {
  env -i PATH="$NODE_DIR:/usr/bin:/bin" HOME="$ISOLATED" XDG_CONFIG_HOME="$ISOLATED/.config" \
    CLOUDFLARE_API_TOKEN="$TOKEN" CLOUDFLARE_ACCOUNT_ID="$ACCOUNT" WRANGLER_SEND_METRICS=false \
    "$WRANGLER" "$@"
}

echo "Checking the token against account $ACCOUNT and Pages project $PROJECT..."
if ! cf pages project list 2>"$ISOLATED/err" | grep -q "[[:space:]]$PROJECT[[:space:]]"; then
  echo "The token can't see the Pages project $PROJECT in account $ACCOUNT. Nothing was deployed." >&2
  sed 's/^/  /' "$ISOLATED/err" >&2
  exit 1
fi
echo "OK: the token reaches $PROJECT."
[ "$CHECK_ONLY" = yes ] && exit 0

python3 "$HERE/build.py"
cf pages deploy "$HERE/dist" --project-name "$PROJECT" --branch main --commit-dirty=true
