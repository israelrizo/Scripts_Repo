#!/bin/bash
# One-time setup of the web UI on the Master. Run from /opt/Scripts_Repo/webapp as a sudoer.
set -euo pipefail
cd "$(dirname "$0")/.."
id jmeter >/dev/null 2>&1 || sudo useradd --system --create-home --shell /bin/bash jmeter
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q
[ -f /etc/jmeter-control-center.env ] || sudo install -m 600 -o jmeter config.env.example /etc/jmeter-control-center.env
sudo chown -R jmeter:jmeter "$(cd .. && pwd)"
sudo cp deploy/jmeter-control-center.service /etc/systemd/system/
sudo systemctl daemon-reload
echo
echo "Next:"
echo "  1) sudo vi /etc/jmeter-control-center.env     (slave IPs, paths)"
echo "  2) sudo -u jmeter ./.venv/bin/python manage_users.py add <you> --role admin"
echo "  3) sudo systemctl enable --now jmeter-control-center"
echo "  4) From your laptop: aws ssm start-session --target <master-id> --document-name AWS-StartPortForwardingSession --parameters portNumber=8090,localPortNumber=8090"
