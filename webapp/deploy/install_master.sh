#!/bin/bash
# One-time setup of the web UI on the Master. Works wherever the repo lives
# (e.g. /mnt/jmeter/JMeter_Scripts/jmeter-framework). Run as a sudoer:
#   cd <repo>/webapp && ./deploy/install_master.sh
# Optional: SERVICE_USER=<user> (default: owner of the repo folder, so results/ stay writable).
set -euo pipefail
WEBAPP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$WEBAPP_DIR/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-$(stat -c %U "$REPO_ROOT")}"
ENV_FILE=/etc/jmeter-control-center.env

echo "Repo root   : $REPO_ROOT"
echo "Web app     : $WEBAPP_DIR"
echo "Service user: $SERVICE_USER"

# jmeter as the service user sees it in a login shell (systemd does not read profile files)
JMETER_BIN="$(sudo -u "$SERVICE_USER" bash -lc 'command -v jmeter' || true)"
if [ -z "$JMETER_BIN" ]; then
    echo "WARNING: 'jmeter' not found on $SERVICE_USER's login PATH; set SR_JMETER_BIN in $ENV_FILE"
else
    JMETER_BIN="$(readlink -f "$JMETER_BIN")"
    echo "JMeter      : $JMETER_BIN"
fi

# venv and private state owned by the service user (nothing else in the repo is touched)
sudo -u "$SERVICE_USER" python3 -m venv "$WEBAPP_DIR/.venv"
sudo -u "$SERVICE_USER" "$WEBAPP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$SERVICE_USER" "$WEBAPP_DIR/.venv/bin/pip" install -q -r "$WEBAPP_DIR/requirements.txt"
sudo -u "$SERVICE_USER" mkdir -p "$WEBAPP_DIR/instance"
chmod 700 "$WEBAPP_DIR/instance"

if [ ! -f "$ENV_FILE" ]; then
    sed -e "s#^SR_REPO_ROOT=.*#SR_REPO_ROOT=$REPO_ROOT#" \
        -e "s#^SR_INSTANCE_DIR=.*#SR_INSTANCE_DIR=$WEBAPP_DIR/instance#" \
        -e "s#^SR_SLAVE_REPO_ROOT=.*#SR_SLAVE_REPO_ROOT=$REPO_ROOT#" \
        -e "s#^\# *SR_JMETER_BIN=.*#SR_JMETER_BIN=${JMETER_BIN}#" \
        "$WEBAPP_DIR/config.env.example" | sudo tee "$ENV_FILE" >/dev/null
    sudo chown "root:$(id -gn "$SERVICE_USER")" "$ENV_FILE"
    sudo chmod 640 "$ENV_FILE"
    echo "Created $ENV_FILE"
else
    echo "$ENV_FILE already exists, left untouched"
fi

sed -e "s#@WEBAPP_DIR@#$WEBAPP_DIR#g" -e "s#@SERVICE_USER@#$SERVICE_USER#g" \
    "$WEBAPP_DIR/deploy/jmeter-control-center.service" | sudo tee /etc/systemd/system/jmeter-control-center.service >/dev/null
sudo systemctl daemon-reload

echo
echo "Next:"
echo "  1) sudo vi $ENV_FILE     (slave IPs, Influx/Grafana, Confluence hosts)"
echo "  2) sudo -u $SERVICE_USER $WEBAPP_DIR/.venv/bin/python $WEBAPP_DIR/manage_users.py add <you> --role admin"
echo "  3) sudo systemctl enable --now jmeter-control-center && journalctl -u jmeter-control-center -f"
echo "  4) Laptop: aws ssm start-session --target <master-instance-id> --document-name AWS-StartPortForwardingSession --parameters portNumber=8090,localPortNumber=8090"
