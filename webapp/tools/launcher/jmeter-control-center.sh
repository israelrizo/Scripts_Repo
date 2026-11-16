#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# JMeter Control Center launcher (engineer computer: macOS / Linux / WSL)
# Starts the Control Center locally on http://localhost:8090 and opens the browser.
# The app drives the Master and Slaves with your AWS CLI session (SSM), so keep
# your AWS profile signed in (the app has an "AWS SSO login" button too).
# Config: ~/.jmeter-control-center.conf  (JMCC_HOME = your clone of the scripts repo)
# Closing this window stops the app (and its SSM tunnels). Tests already running
# on the Master keep running; the app re-attaches to them next time.
# ------------------------------------------------------------------------------
set -o pipefail   # no -u: macOS bash 3.2 treats empty arrays as unbound
CONF="${JMCC_CONF:-$HOME/.jmeter-control-center.conf}"
# shellcheck disable=SC1090
[ -f "$CONF" ] && source "$CONF"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -z "${JMCC_HOME:-}" ] && [ -f "$HERE/../../run.py" ]; then JMCC_HOME="$(cd "$HERE/../../.." && pwd)"; fi
WEBAPP="${JMCC_HOME:-}/webapp"
PORT="${PORT:-8090}"
URL="http://localhost:${PORT}"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
pause_exit() { read -r -p "Press Enter to close" _; exit "${1:-1}"; }
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- ; }
open_url() {
  if command -v open >/dev/null; then open "$1"
  elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1
  elif command -v wslview >/dev/null; then wslview "$1"
  else echo "Open $1 in your browser"; fi
}

if [ ! -f "$WEBAPP/run.py" ]; then
  echo "Cannot find the scripts repository. Set JMCC_HOME in $CONF to your clone, e.g.:"
  echo "  JMCC_HOME=\$HOME/Documents/Github/Scripts_Repo"
  pause_exit 1
fi
if port_open "$PORT"; then
  say "Control Center already running, opening $URL"; open_url "$URL"; exit 0
fi
command -v python3 >/dev/null || { echo "python3 not found (install Python 3.9+)"; pause_exit 1; }
command -v aws >/dev/null || echo "WARNING: AWS CLI v2 not found — servers cannot be controlled until it is installed"
command -v session-manager-plugin >/dev/null || echo "WARNING: Session Manager plugin not found — tunnels and report download need it"
command -v git >/dev/null || { echo "git not found"; pause_exit 1; }

cd "$WEBAPP" || pause_exit 1
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import flask, waitress, qrcode, cryptography, defusedxml" 2>/dev/null; then
  say "First start: creating the Python environment (one minute)"
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt || pause_exit 1
fi
if ! .venv/bin/python -c "from srapp import users; import sys; sys.exit(0 if users.count() else 1)" 2>/dev/null; then
  say "Create your Control Center login (local to this computer)"
  read -r -p "Username: " U
  .venv/bin/python manage_users.py add "$U" --role admin || pause_exit 1
fi

export SR_PORT="$PORT" SR_HOST=127.0.0.1 SR_MODE="${SR_MODE:-aws}"
say "Starting JMeter Control Center on $URL  (keep this window open; close it to stop)"
( for _ in $(seq 1 60); do port_open "$PORT" && { open_url "$URL"; break; }; sleep 0.5; done ) &
exec .venv/bin/python run.py
