#!/usr/bin/env bash
# Removes the JMeter Control Center background service (LaunchAgent) of YOUR user. Run it WITHOUT sudo.
#   ./uninstall_macos.sh               service only (settings, users, history and reports are kept)
#   ./uninstall_macos.sh --purge       also the Python environment (.venv), the Launchpad app and launcher config,
#                                      so the next install starts clean (use it when a reinstall fails)
#   ./uninstall_macos.sh --remove-data also webapp/instance (settings, encrypted tokens, users, history) - asks first
set -o pipefail
if [ "$(id -u)" -eq 0 ]; then
  echo "Do not run this with sudo: the service belongs to your macOS user."
  echo "Run:  $0 $*"
  exit 1
fi
WEBAPP="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.bancobase.jmeter-control-center
PURGE=0; DATA=0
for a in "$@"; do case "$a" in --purge) PURGE=1 ;; --remove-data) DATA=1 ;; esac; done

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Service stopped"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" && echo "LaunchAgent removed"
# a copy started from the launcher (its SSM tunnels close with it)
pkill -f "$WEBAPP/.venv/bin/python run.py" 2>/dev/null && echo "App process stopped"

if [ $PURGE -eq 1 ]; then
  rm -rf "$WEBAPP/.venv" && echo "Python environment deleted (.venv)"
  find "$WEBAPP" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  rm -rf "$HOME/Applications/JMeter Control Center.app" "$HOME/.jmeter-control-center.conf" \
         "$HOME/Library/Logs/JMeterControlCenter.log" && echo "Launchpad app, launcher config and log removed"
  BAD="$(find "$WEBAPP" ! -user "$(id -un)" -print 2>/dev/null | head -3)"
  [ -n "$BAD" ] && echo "Note: some files still belong to another user (created with sudo); the installer offers to fix them."
fi
if [ $DATA -eq 1 ]; then
  read -r -p "Delete ALL settings, users, tokens, history and reports in $WEBAPP/instance ? Type DELETE to confirm: " A
  if [ "$A" = "DELETE" ]; then rm -rf "$WEBAPP/instance" && echo "Data deleted"; else echo "Data kept"; fi
fi
if [ -f /etc/sudoers.d/jmeter-control-center ]; then
  read -r -p "Remove the 'pmset schedule wake' sudoers rule too? [y/N] " A
  [[ "$A" =~ ^[Yy] ]] && sudo rm -f /etc/sudoers.d/jmeter-control-center && echo "Wake rule removed"
fi
echo
echo "To install again (no sudo):  $WEBAPP/tools/service/install_macos.sh"
