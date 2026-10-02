# Deployment runbook — EC2 + DynamoDB + DuckDNS

Everything is driven from your laptop by **`deploy/deploy.sh`**; the server
side is **`deploy/server_setup.sh`** (idempotent, re-run any time).

```
deploy/
  deploy.sh               local entry point (setup | update | env | status | logs | restart | ssh)
  server_setup.sh         runs on EC2 as root: packages, venv, systemd, DuckDNS, nginx, HTTPS
  nginx-ttt-arena.conf    reverse-proxy template (SSE/WebSocket + real client IP)
  iam-policy.json         least-privilege DynamoDB policy for an EC2 instance role
  deploy.config.example   copy → deploy.config (git-ignored) and fill in
```

## What ends up on the server

| piece | where | why |
|---|---|---|
| code + venv + `.env` | `/home/<user>/tictactoe-arena` | owned by the login user, so updates need no root except restart |
| `ttt-arena.service` | systemd | starts on boot, restarts on crash (`Restart=always`), logs to journald |
| `duckdns.timer` | systemd, every 5 min + 30 s after boot | EC2 public IP changes on stop/start; DNS follows it |
| nginx | `/etc/nginx/conf.d/ttt-arena.conf` | ports 80/443, TLS, SSE streaming, real client IP for rate limiting |
| certbot | `/opt/certbot` venv + `certbot-renew.timer` | free TLS cert for `<sub>.duckdns.org`, auto-renewed |

## 0. One-time AWS prerequisites (console)

1. **EC2 instance** — Ubuntu 22.04/24.04 or Amazon Linux 2023. A `t3.micro`/
   `t3.small` is plenty (the app is I/O-bound waiting on model APIs).
2. **Security group** inbound:
   - `22` from **your IP only**
   - `80` and `443` from `0.0.0.0/0` (with nginx) — or `7860` if `ENABLE_NGINX=no`
   - close `7860` to the world when nginx is on (the app binds to 127.0.0.1 anyway).
3. **DynamoDB credentials** — recommended: an **IAM role** on the instance with
   `deploy/iam-policy.json` attached (EC2 → Actions → Security → Modify IAM role),
   then **remove** `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from the server's
   `.env`. boto3 picks the role up automatically. Keeping keys in `.env` still
   works; it's just a long-lived secret on disk (D-013).
4. **DuckDNS** — log in at duckdns.org, create a subdomain, copy the token.

## 1. First deploy

```bash
cp deploy/deploy.config.example deploy/deploy.config
$EDITOR deploy/deploy.config        # EC2_HOST, EC2_USER, SSH_KEY, DUCKDNS_*, CERTBOT_EMAIL
./deploy/deploy.sh setup
```

`setup` = upload code → upload `.env` (only if the server has none) → run
`server_setup.sh` → health-check → print the public URL.

With `ENABLE_HTTPS=yes` the script accepts Let's Encrypt's terms of service
on your behalf (`--agree-tos`) using `CERTBOT_EMAIL`.

> **Coming from the current manual setup?** If the app is already running by
> hand (`nohup python app.py`, `screen`, tmux…), stop that process first so
> port 7860 is free, then run `setup`. If you already have a DuckDNS cron job,
> remove it (`crontab -e`) — the systemd timer replaces it.

## 2. Everyday commands

```bash
./deploy/deploy.sh update     # after code changes: push, pip install, restart, health-check
./deploy/deploy.sh env        # after editing local .env (new API key, limits)
./deploy/deploy.sh logs       # tail app logs
./deploy/deploy.sh status     # service + DuckDNS timer state
./deploy/deploy.sh restart
./deploy/deploy.sh ssh
```

Changed `deploy.config` (port, domain, nginx/https flags)? Run `setup` again.

## 3. Troubleshooting

| symptom | check |
|---|---|
| `setup` stops at certbot | DNS not pointing yet: `dig +short <sub>.duckdns.org` must equal the EC2 public IP; port 80 must be open; re-run `setup` |
| site loads but game never updates | nginx buffering SSE — make sure the installed conf has `proxy_buffering off` |
| everyone shares the same "games left" | nginx not sending `X-Forwarded-For $remote_addr`, or app not bound to 127.0.0.1 |
| health check fails | `deploy.sh logs`; usually missing `.env` / API key (`SystemExit: No API keys`) or AWS permissions |
| `AccessDeniedException` from DynamoDB | IAM role missing an action from `iam-policy.json`, or wrong `AWS_REGION` |
| domain points to old IP after stop/start | `sudo systemctl start duckdns.service && journalctl -u duckdns -n5` (should say `OK`) |
| `No API keys found` crash loop | `.env` missing on server → `deploy.sh env` |

## 4. Not covered (on purpose)

- **Creating** the EC2 instance / security group / IAM role — one-time console
  clicks; scripting them (Terraform/CDK) isn't worth it for one box (D-015).
- **Zero-downtime deploys** — a restart takes ~5 s; acceptable for a demo app.
- **Elastic IP** — optional; DuckDNS makes it unnecessary (D-011).
