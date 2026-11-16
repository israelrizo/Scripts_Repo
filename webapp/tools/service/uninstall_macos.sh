#!/usr/bin/env bash
# Removes the JMeter Control Center background service (LaunchAgent). Your data in webapp/instance is kept.
LABEL=com.bancobase.jmeter-control-center
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Service stopped"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" && echo "LaunchAgent removed"
if [ -f /etc/sudoers.d/jmeter-control-center ]; then
  read -r -p "Remove the 'pmset schedule wake' sudoers rule too? [y/N] " A
  [[ "$A" =~ ^[Yy] ]] && sudo rm -f /etc/sudoers.d/jmeter-control-center && echo "Wake rule removed"
fi
