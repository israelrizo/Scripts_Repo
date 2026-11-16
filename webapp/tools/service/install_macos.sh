#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Installs the JMeter Control Center as a per-user background service on macOS (LaunchAgent):
#   * starts at login and restarts after a crash — schedules fire without opening the app
#   * keeps the Mac awake while a test runs or a scheduled run is close (caffeinate)
#   * optional: lets the service wake the Mac from sleep before each scheduled run
#     (sudoers rule limited to "pmset schedule wake")
# No admin rights needed except for that optional rule.
#   ./install_macos.sh            install / update and start
#   ./install_macos.sh --dry-run  only print the LaunchAgent that would be installed
# Uninstall: ./uninstall_macos.sh
# ------------------------------------------------------------------------------
set -o pipefail
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
WEBAPP="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.bancobase.jmeter-control-center
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/JMeterControlCenter.log"
PORT=8090
say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- ; }
xml() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

[ -f "$WEBAPP/run.py" ] || { echo "run.py not found under $WEBAPP"; exit 1; }
cd "$WEBAPP" || exit 1

if [ $DRY -eq 0 ]; then
  command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
  for b in git aws session-manager-plugin; do command -v "$b" >/dev/null || echo "WARNING: $b not found on PATH"; done
  if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import flask, waitress, qrcode, cryptography, defusedxml" 2>/dev/null; then
    say "Creating the Python environment"
    python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt || exit 1
  fi
  if ! .venv/bin/python -c "from srapp import users; import sys; sys.exit(0 if users.count() else 1)" 2>/dev/null; then
    say "Create your Control Center login"
    read -r -p "Username: " U
    .venv/bin/python manage_users.py add "$U" --role admin || exit 1
  fi
fi

# launchd starts with a minimal PATH: add the folders of aws, git, session-manager-plugin
P="/usr/bin:/bin:/usr/sbin:/sbin"
for b in aws git session-manager-plugin; do
  d="$(dirname "$(command -v "$b" 2>/dev/null)" 2>/dev/null)"
  [ -n "$d" ] && [ "$d" != "." ] && case ":$P:" in *":$d:"*) ;; *) P="$d:$P" ;; esac
done
for d in /opt/homebrew/bin /usr/local/bin; do [ -d "$d" ] && case ":$P:" in *":$d:"*) ;; *) P="$P:$d" ;; esac; done

CONTENT=$(cat <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$WEBAPP/.venv/bin/python")</string>
    <string>run.py</string>
    <string>--service</string>
    <string>macos-launchagent</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$WEBAPP")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$(xml "$P")</string>
    <key>HOME</key><string>$(xml "$HOME")</string>
    <key>LANG</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOG")</string>
</dict>
</plist>
PL
)

if [ $DRY -eq 1 ]; then echo "$CONTENT"; exit 0; fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
if port_open $PORT && ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT (the app opened from the launcher?). Close it and run this again."
  exit 1
fi
printf '%s\n' "$CONTENT" > "$PLIST"
plutil -lint "$PLIST" >/dev/null || { echo "Invalid plist"; exit 1; }
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" || { echo "launchctl bootstrap failed"; exit 1; }
launchctl enable "gui/$(id -u)/$LABEL"
say "Service installed: $LABEL (log: $LOG and webapp/instance/service.log)"

for _ in $(seq 1 40); do port_open $PORT && break; sleep 0.5; done
if port_open $PORT; then say "Running on http://localhost:$PORT"; open "http://localhost:$PORT"
else echo "The service did not open port $PORT yet; check $LOG"; fi

if [ ! -f /etc/sudoers.d/jmeter-control-center ]; then
  echo
  read -r -p "Allow the service to WAKE this Mac from sleep before scheduled runs? Adds a sudoers rule limited to 'pmset schedule wake' (asks for your password) [y/N] " A
  if [[ "$A" =~ ^[Yy] ]]; then
    TMP="$(mktemp)"
    echo "$(id -un) ALL=(root) NOPASSWD: /usr/bin/pmset schedule wake *" > "$TMP"
    if sudo visudo -cf "$TMP" >/dev/null && sudo install -m 0440 -o root -g wheel "$TMP" /etc/sudoers.d/jmeter-control-center; then
      say "Wake rule installed"
    else
      echo "Could not install the sudoers rule (schedules still fire while the Mac is awake)"
    fi
    rm -f "$TMP"
  fi
fi
echo
echo "Tip: System Settings → Battery → Options → 'Prevent automatic sleeping on power adapter when the display is off'"
echo "     keeps a plugged-in Mac able to run night schedules even with the screen off."
