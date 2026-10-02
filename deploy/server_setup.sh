#!/usr/bin/env bash
# server_setup.sh — runs ON the EC2 instance as root (deploy.sh calls it).
# Idempotent: safe to re-run; every step overwrites its own files.
#
#   sudo bash server_setup.sh <path/to/deploy.config> <app-user>
#
# Works on Ubuntu 22.04/24.04 (apt) and Amazon Linux 2023 (dnf).
set -euo pipefail

CONFIG="${1:?usage: server_setup.sh <deploy.config> <app-user>}"
APP_USER="${2:?usage: server_setup.sh <deploy.config> <app-user>}"
# shellcheck source=/dev/null
source "$CONFIG"
APP_PORT="${APP_PORT:-7860}"
HUMAN_CONCURRENCY="${HUMAN_CONCURRENCY:-8}"
ENABLE_NGINX="${ENABLE_NGINX:-yes}"
ENABLE_HTTPS="${ENABLE_HTTPS:-no}"
DOMAIN=""
[[ -n "${DUCKDNS_SUBDOMAIN:-}" ]] && DOMAIN="$DUCKDNS_SUBDOMAIN.duckdns.org"

log() { printf '\033[1;36m[setup] %s\033[0m\n' "$*"; }
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)"; exit 1; }

# ── 1. System packages ───────────────────────────────────────────────────────
log "Installing system packages"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip curl tar
  [[ "$ENABLE_NGINX" == "yes" ]] && apt-get install -y -qq nginx
elif command -v dnf >/dev/null; then
  # AL2023's default python3 is 3.9; Gradio 6 needs >= 3.10.
  dnf install -y -q python3.11 python3.11-pip tar
  command -v curl >/dev/null || dnf install -y -q curl-minimal
  [[ "$ENABLE_NGINX" == "yes" ]] && dnf install -y -q nginx
else
  echo "Unsupported distro (need apt or dnf)"; exit 1
fi

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3,10))'; then
    PY="$(command -v "$c")"; break
  fi
done
[[ -n "$PY" ]] || { echo "Need Python >= 3.10"; exit 1; }
log "Using $PY ($("$PY" --version))"

# ── 2. Virtualenv + dependencies (as the app user, not root) ─────────────────
log "Creating venv and installing requirements"
chown -R "$APP_USER:" "$APP_DIR"
sudo -u "$APP_USER" bash -c "
  cd '$APP_DIR'
  [[ -x venv/bin/python ]] || '$PY' -m venv venv
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q -r requirements.txt
"
[[ -f "$APP_DIR/.env" ]] || log "WARNING: $APP_DIR/.env missing — app will exit until you run: deploy.sh env"

# ── 3. systemd service: start on boot, restart on crash ──────────────────────
log "Installing systemd unit ttt-arena.service"
BIND_HOST="0.0.0.0"
[[ "$ENABLE_NGINX" == "yes" ]] && BIND_HOST="127.0.0.1"   # only reachable via nginx
cat > /etc/systemd/system/ttt-arena.service <<EOF
[Unit]
Description=Tic-Tac-Toe Model Arena (Gradio)
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR/src
Environment=HOST=$BIND_HOST
Environment=PORT=$APP_PORT
Environment=HUMAN_CONCURRENCY=$HUMAN_CONCURRENCY
Environment=PYTHONUNBUFFERED=1
Environment=GRADIO_ANALYTICS_ENABLED=False
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable ttt-arena >/dev/null
systemctl restart ttt-arena

# ── 4. DuckDNS: keep <sub>.duckdns.org pointed at this instance's IP ─────────
# The EC2 public IP changes on every stop/start (unless you use an Elastic IP),
# so a timer re-registers it every 5 minutes and right after boot.
if [[ -n "$DOMAIN" && -n "${DUCKDNS_TOKEN:-}" ]]; then
  log "Installing DuckDNS updater for $DOMAIN"
  install -d -m 700 /etc/ttt-arena
  umask 077
  printf 'DUCKDNS_SUBDOMAIN=%s\nDUCKDNS_TOKEN=%s\n' "$DUCKDNS_SUBDOMAIN" "$DUCKDNS_TOKEN" > /etc/ttt-arena/duckdns.env
  umask 022
  cat > /usr/local/bin/duckdns-update <<'EOF'
#!/usr/bin/env bash
# Empty ip= → DuckDNS uses the address the request comes from (our public IP).
set -euo pipefail
source /etc/ttt-arena/duckdns.env
resp=$(curl -fsS --max-time 15 "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=")
echo "duckdns: $resp"
[[ "$resp" == OK* ]]
EOF
  chmod 755 /usr/local/bin/duckdns-update
  cat > /etc/systemd/system/duckdns.service <<'EOF'
[Unit]
Description=Update DuckDNS record
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/duckdns-update
EOF
  cat > /etc/systemd/system/duckdns.timer <<'EOF'
[Unit]
Description=Update DuckDNS every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now duckdns.timer >/dev/null
  systemctl start duckdns.service || log "WARNING: DuckDNS update failed — check token/subdomain"
else
  log "DuckDNS not configured — skipping"
fi

# ── 5. nginx reverse proxy ───────────────────────────────────────────────────
if [[ "$ENABLE_NGINX" == "yes" ]]; then
  log "Configuring nginx → 127.0.0.1:$APP_PORT"
  sed -e "s/__SERVER_NAME__/${DOMAIN:-_}/" -e "s/__APP_PORT__/$APP_PORT/" \
      "$APP_DIR/deploy/nginx-ttt-arena.conf" > /etc/nginx/conf.d/ttt-arena.conf
  # Ubuntu's "Welcome to nginx" default site would otherwise answer bare-IP requests.
  rm -f /etc/nginx/sites-enabled/default
  [[ -n "$DOMAIN" ]] || log "NOTE: no DUCKDNS_SUBDOMAIN — nginx matches any host (server_name _)"
  # Amazon Linux ships SELinux; let nginx talk to the local app port.
  if command -v getenforce >/dev/null && [[ "$(getenforce)" == "Enforcing" ]]; then
    setsebool -P httpd_can_network_connect 1
  fi
  nginx -t
  systemctl enable nginx >/dev/null
  systemctl restart nginx
fi

# ── 6. HTTPS via Let's Encrypt (certbot in its own venv: same on every distro)
if [[ "$ENABLE_NGINX" == "yes" && "$ENABLE_HTTPS" == "yes" ]]; then
  [[ -n "$DOMAIN" ]] || { echo "ENABLE_HTTPS needs DUCKDNS_SUBDOMAIN"; exit 1; }
  log "Obtaining/installing TLS certificate for $DOMAIN"
  if [[ ! -x /opt/certbot/bin/certbot ]]; then
    "$PY" -m venv /opt/certbot
    /opt/certbot/bin/pip install -q --upgrade pip
    /opt/certbot/bin/pip install -q certbot certbot-nginx
  fi
  # --keep-until-expiring reuses an existing cert but still re-installs it
  # into the freshly rewritten nginx config above.
  /opt/certbot/bin/certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
      -m "${CERTBOT_EMAIL:?set CERTBOT_EMAIL}" --redirect --keep-until-expiring
  cat > /etc/systemd/system/certbot-renew.service <<'EOF'
[Unit]
Description=Renew Let's Encrypt certificates

[Service]
Type=oneshot
ExecStart=/opt/certbot/bin/certbot renew -q --deploy-hook "systemctl reload nginx"
EOF
  cat > /etc/systemd/system/certbot-renew.timer <<'EOF'
[Unit]
Description=Twice-daily certbot renew check

[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now certbot-renew.timer >/dev/null
fi

log "Done. Security group must allow: 22 (your IP)$([[ "$ENABLE_NGINX" == "yes" ]] && echo ", 80, 443" || echo ", $APP_PORT")"
