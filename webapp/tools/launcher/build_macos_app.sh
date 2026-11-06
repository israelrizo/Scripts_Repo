#!/usr/bin/env bash
# Builds "JMeter Control Center.app" (Dock / Launchpad icon) that runs the launcher in Terminal.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/JMeter Control Center.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$HOME/.jmeter-control-center"
cp "$HERE/jmeter-control-center.sh" "$HOME/.jmeter-control-center/launcher.sh"
chmod +x "$HOME/.jmeter-control-center/launcher.sh"
cp "$HERE/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/MacOS/JMeterControlCenter" <<'SH'
#!/bin/bash
osascript -e 'tell application "Terminal" to activate' \
          -e 'tell application "Terminal" to do script "bash ~/.jmeter-control-center/launcher.sh"'
SH
chmod +x "$APP/Contents/MacOS/JMeterControlCenter"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>JMeter Control Center</string>
  <key>CFBundleDisplayName</key><string>JMeter Control Center</string>
  <key>CFBundleIdentifier</key><string>com.bancobase.qaperformance.jmcc</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>JMeterControlCenter</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict></plist>
PLIST
touch "$APP"
[ -f "$HOME/.jmeter-control-center.conf" ] || cp "$HERE/jmeter-control-center.conf.example" "$HOME/.jmeter-control-center.conf"
echo "Created: $APP"
echo "Edit ~/.jmeter-control-center.conf (INSTANCE_ID, AWS_PROFILE) and open the app from Finder / Launchpad."
