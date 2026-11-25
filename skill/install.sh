#!/bin/sh
# Install or update CheckIn's skill for AI agents (D-028).
#
# Served by a CheckIn app to a signed-in person, at a personal link that expires
# (the API tokens page shows it, in the text to paste into an agent):
#   curl -fsSL <link>/install.sh | sh
#   curl -fsSL <link>/install.sh | sh -s -- --dir ~/.agents/skills
#
# Puts the skill in <dir>/checkin (default: Claude Code's skills folder,
# ${CLAUDE_CONFIG_DIR:-~/.claude}/skills). Checks the download against the
# checksum the website publishes, and replaces an older copy only once the new
# one is complete. Needs python3 and curl (or wget). Running it again updates.
set -eu

BASE="{{BASE}}"
DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    *) echo "unknown option: $1 (only --dir DIR)" >&2; exit 2 ;;
  esac
done
[ -n "$DIR" ] || DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"
command -v python3 >/dev/null 2>&1 || { echo "CheckIn's skill needs python3" >&2; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"; else wget -q "$1" -O "$2"; fi
}
fetch "$BASE/version.json" "$TMP/version.json"
fetch "$BASE/checkin.zip" "$TMP/checkin.zip"
mkdir -p "$DIR"

python3 - "$TMP" "$DIR" <<'PY'
import hashlib, json, os, shutil, sys, tempfile, zipfile
tmp, parent = sys.argv[1], os.path.abspath(sys.argv[2])
info = json.load(open(os.path.join(tmp, "version.json")))
raw = open(os.path.join(tmp, "checkin.zip"), "rb").read()
if hashlib.sha256(raw).hexdigest() != info["sha256"]:
    sys.exit("the download doesn't match its checksum; nothing was installed")
work = tempfile.mkdtemp(prefix=".checkin-install-", dir=parent)
try:
    with zipfile.ZipFile(os.path.join(tmp, "checkin.zip")) as z:
        for name in z.namelist():
            if not os.path.abspath(os.path.join(work, name)).startswith(work + os.sep):
                sys.exit(f"unsafe path in the download: {name}")
        z.extractall(work)
    target, old = os.path.join(parent, "checkin"), os.path.join(parent, "checkin.old")
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(target):
        os.rename(target, old)
    os.rename(os.path.join(work, "checkin"), target)
    shutil.rmtree(old, ignore_errors=True)
    os.chmod(os.path.join(target, "scripts", "checkin.py"), 0o755)
finally:
    shutil.rmtree(work, ignore_errors=True)
print(f"CheckIn skill {info['version']} installed in {target}")
PY
echo "Next: ask your agent to sign in to CheckIn (it shows a link to approve; it never needs your password)."
