#!/usr/bin/env bash
# deploy.sh — run from your laptop to deploy the arena to EC2.
#
#   ./deploy/deploy.sh setup     first time: push code + .env, install everything
#   ./deploy/deploy.sh update    push new code, reinstall deps if changed, restart
#   ./deploy/deploy.sh env       upload local .env (API keys) and restart
#   ./deploy/deploy.sh status    systemd status of app + DuckDNS timer
#   ./deploy/deploy.sh logs      follow app logs (Ctrl-C to stop)
#   ./deploy/deploy.sh restart   restart the app
#   ./deploy/deploy.sh ssh       open a shell on the instance
#
# Config is read from deploy/deploy.config (copy deploy.config.example).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$ROOT/deploy/deploy.config"
[[ -f "$CONFIG" ]] || { echo "Missing $CONFIG — cp deploy/deploy.config.example deploy/deploy.config"; exit 1; }
# shellcheck source=/dev/null
source "$CONFIG"

: "${EC2_HOST:?set EC2_HOST}" "${EC2_USER:?set EC2_USER}" "${SSH_KEY:?set SSH_KEY}" "${APP_DIR:?set APP_DIR}"
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
TARGET="$EC2_USER@$EC2_HOST"
SERVICE="ttt-arena"

log()  { printf '\033[1;33m▶ %s\033[0m\n' "$*"; }
remote() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; }

# Ship code as a tarball over ssh (no rsync/git needed on the server).
# Excludes secrets and local junk; .env goes separately via `env`.
push_code() {
  log "Uploading code to $TARGET:$APP_DIR"
  remote "mkdir -p '$APP_DIR'"
  tar -C "$ROOT" -czf - \
      --exclude='__pycache__' --exclude='*.pyc' \
      src requirements.txt deploy \
    | remote "tar -xzf - -C '$APP_DIR' && chmod 600 '$APP_DIR/deploy/deploy.config'"
}

push_env() {
  [[ -f "$ROOT/.env" ]] || { echo "No local .env to upload"; exit 1; }
  log "Uploading .env (chmod 600)"
  remote "umask 077 && cat > '$APP_DIR/.env'" < "$ROOT/.env"
}

public_url() {
  local host="$EC2_HOST" scheme="http" port=""
  [[ -n "${DUCKDNS_SUBDOMAIN:-}" ]] && host="$DUCKDNS_SUBDOMAIN.duckdns.org"
  [[ "${ENABLE_NGINX:-yes}" == "yes" ]] || port=":${APP_PORT:-7860}"
  [[ "${ENABLE_NGINX:-yes}" == "yes" && "${ENABLE_HTTPS:-no}" == "yes" ]] && scheme="https"
  echo "$scheme://$host$port"
}

health() {
  log "Health check"
  for _ in $(seq 1 20); do
    if remote "curl -fsS -o /dev/null http://127.0.0.1:${APP_PORT:-7860}/"; then
      echo "✔ app is answering on port ${APP_PORT:-7860} → $(public_url)"
      return 0
    fi
    sleep 3
  done
  echo "✘ app did not come up — recent logs:"
  remote "sudo journalctl -u $SERVICE -n 40 --no-pager"
  exit 1
}

case "${1:-}" in
  setup)
    push_code
    if remote "test -f '$APP_DIR/.env'"; then
      log ".env already on server — keeping it (use 'env' to overwrite)"
    else
      push_env
    fi
    log "Running server_setup.sh (packages, venv, systemd, DuckDNS, nginx, HTTPS)"
    remote "sudo bash '$APP_DIR/deploy/server_setup.sh' '$APP_DIR/deploy/deploy.config' '$EC2_USER'"
    health
    ;;
  update)
    push_code
    log "Installing dependencies (fast no-op if unchanged) and restarting"
    remote "cd '$APP_DIR' && ./venv/bin/pip install -q -r requirements.txt && sudo systemctl restart $SERVICE"
    health
    ;;
  env)
    push_env
    remote "sudo systemctl restart $SERVICE"
    health
    ;;
  status)  remote "systemctl status $SERVICE --no-pager; systemctl list-timers duckdns.timer --no-pager" ;;
  logs)    remote "sudo journalctl -u $SERVICE -f" ;;
  restart) remote "sudo systemctl restart $SERVICE"; health ;;
  ssh)     ssh "${SSH_OPTS[@]}" "$TARGET" ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
