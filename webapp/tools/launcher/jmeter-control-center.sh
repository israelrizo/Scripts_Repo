#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# JMeter Control Center launcher (engineer laptop: macOS / Linux / WSL)
# Opens the SSM port forwards to the JMeter Master and the Control Center in the browser:
#   localhost:8090 -> Master 127.0.0.1:8090 (Control Center)
#   localhost:3000 -> Master 127.0.0.1:3000 (Grafana, optional)
# Needs: AWS CLI v2 + Session Manager plugin + an AWS profile allowed to use SSM on the Master.
# Config: ~/.jmeter-control-center.conf (see jmeter-control-center.conf.example)
# ------------------------------------------------------------------------------
set -o pipefail   # no -u: macOS bash 3.2 treats empty arrays as unbound
CONF="${JMCC_CONF:-$HOME/.jmeter-control-center.conf}"
[ -f "$CONF" ] || CONF="$(cd "$(dirname "$0")" && pwd)/jmeter-control-center.conf"
if [ ! -f "$CONF" ]; then
  echo "Missing config. Copy jmeter-control-center.conf.example to ~/.jmeter-control-center.conf and fill INSTANCE_ID."
  read -r -p "Press Enter to close" _; exit 1
fi
# shellcheck disable=SC1090
source "$CONF"
: "${INSTANCE_ID:?Set INSTANCE_ID in $CONF}"
LOCAL_PORT="${LOCAL_PORT:-8090}"
REMOTE_PORT="${REMOTE_PORT:-8090}"
GRAFANA_LOCAL_PORT="${GRAFANA_LOCAL_PORT:-3000}"
GRAFANA_REMOTE_PORT="${GRAFANA_REMOTE_PORT:-3000}"
FORWARD_GRAFANA="${FORWARD_GRAFANA:-yes}"
AWS_ARGS=()
[ -n "${AWS_PROFILE:-}" ] && AWS_ARGS+=(--profile "$AWS_PROFILE")
[ -n "${AWS_REGION:-}" ] && AWS_ARGS+=(--region "$AWS_REGION")
URL="http://localhost:${LOCAL_PORT}"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3>&- ; }
open_url() {
  if command -v open >/dev/null; then open "$1"
  elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1
  elif command -v wslview >/dev/null; then wslview "$1"
  else echo "Open $1 in your browser"; fi
}

command -v aws >/dev/null || { echo "AWS CLI v2 not found (https://aws.amazon.com/cli/)"; read -r -p "Enter to close" _; exit 1; }
command -v session-manager-plugin >/dev/null || { echo "Session Manager plugin not found (AWS docs: install the Session Manager plugin)"; read -r -p "Enter to close" _; exit 1; }

if port_open "$LOCAL_PORT"; then
  say "Port $LOCAL_PORT already forwarded, opening $URL"
  open_url "$URL"; exit 0
fi

if [ -n "${AWS_SSO_LOGIN:-}" ] && ! aws sts get-caller-identity ${AWS_ARGS[@]+"${AWS_ARGS[@]}"} >/dev/null 2>&1; then
  say "AWS session expired, running aws sso login"
  aws sso login ${AWS_ARGS[@]+"${AWS_ARGS[@]}"} || exit 1
fi

PIDS=()
cleanup() { say "Closing tunnels"; for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null; done; exit 0; }
trap cleanup INT TERM EXIT

forward() {  # local remote label
  say "Forwarding localhost:$1 -> ${INSTANCE_ID}:$2 ($3)"
  aws ssm start-session ${AWS_ARGS[@]+"${AWS_ARGS[@]}"} --target "$INSTANCE_ID" \
    --document-name AWS-StartPortForwardingSession \
    --parameters "{\"portNumber\":[\"$2\"],\"localPortNumber\":[\"$1\"]}" >/tmp/jmcc-ssm-$1.log 2>&1 &
  PIDS+=("$!")
}

forward "$LOCAL_PORT" "$REMOTE_PORT" "Control Center"
if [ "$FORWARD_GRAFANA" = "yes" ] && ! port_open "$GRAFANA_LOCAL_PORT"; then
  forward "$GRAFANA_LOCAL_PORT" "$GRAFANA_REMOTE_PORT" "Grafana"
fi

for _ in $(seq 1 40); do
  port_open "$LOCAL_PORT" && break
  if ! kill -0 "${PIDS[0]}" 2>/dev/null; then
    echo "SSM session failed:"; cat "/tmp/jmcc-ssm-$LOCAL_PORT.log"; read -r -p "Enter to close" _; exit 1
  fi
  sleep 0.5
done
say "Ready: $URL   (keep this window open; Ctrl+C or close it to disconnect)"
open_url "$URL"
wait "${PIDS[0]}"
