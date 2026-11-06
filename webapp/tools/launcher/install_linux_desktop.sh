#!/usr/bin/env bash
# Adds "JMeter Control Center" to the Linux application menu with its icon.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.jmeter-control-center" "$HOME/.local/share/applications" "$HOME/.local/share/icons"
cp "$HERE/jmeter-control-center.sh" "$HOME/.jmeter-control-center/launcher.sh"
chmod +x "$HOME/.jmeter-control-center/launcher.sh"
cp "$HERE/icon-512.png" "$HOME/.local/share/icons/jmeter-control-center.png"
cat > "$HOME/.local/share/applications/jmeter-control-center.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=JMeter Control Center
Comment=Open the SSM tunnel to the JMeter Master and the Control Center
Exec=bash $HOME/.jmeter-control-center/launcher.sh
Icon=$HOME/.local/share/icons/jmeter-control-center.png
Terminal=true
Categories=Development;Network;
DESK
[ -f "$HOME/.jmeter-control-center.conf" ] || cp "$HERE/jmeter-control-center.conf.example" "$HOME/.jmeter-control-center.conf"
echo "Installed. Edit ~/.jmeter-control-center.conf and look for 'JMeter Control Center' in your app menu."
