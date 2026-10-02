# Decision log

Format per entry: **Context** (what forced a choice) → **Decision** → **Why** →
**Consequences / trade-offs**. Append new entries; supersede rather than edit.
Entries D-001 to D-004 are *(reconstructed)* from the 2026-09-19 code.

---

## D-001 · Gradio for the UI — 2026-09-19 *(reconstructed)*
**Context:** Need a live-updating board plus panels for a Python-only project.
**Decision:** Gradio `Blocks`, with the arena rendered as one `gr.HTML` string (SVG board + panels).
**Why:** Generators give live streaming of each move for free; one Python file, no frontend build.
**Consequences:** Custom look comes from inline CSS. Interactivity beyond buttons needs `gr.HTML` + JS (see D-005).

## D-002 · Single `app.py` + small `db.py` — 2026-09-19 *(reconstructed)*
**Context:** Small hobby/demo project.
**Decision:** Keep game logic, rendering and UI in one file; isolate persistence in `db.py`.
**Why:** Easy to read top-to-bottom; the DB layer is the only part you'd swap or stub (as `TESTING.md` does).
**Consequences:** If the file grows past ~800 lines, split `engine.py` / `render.py` first.

## D-003 · DynamoDB, on-demand, TTL — 2026-09-19 *(reconstructed)*
**Context:** Need rate-limit counters and game logs on a tiny budget.
**Decision:** Two tables, `PAY_PER_REQUEST`, TTL on `expires_at`, auto-created at startup.
**Why:** Effectively free at this traffic; TTL deletes old windows/logs automatically, so there's no cleanup job.
**Consequences:** TTL deletion is lazy (can lag up to ~48 h), so the code checks `expires_at` itself instead of trusting row absence.

## D-004 · Rate limit keyed on `name#ip`, counted at game start — 2026-09-19 *(reconstructed)*
**Context:** Protect API spend without accounts/login.
**Decision:** `MAX_GAMES` per `RATE_WINDOW_HOURS` per lowercased-name + IP; increment before the game runs.
**Why:** Counting at start means abandoning a game can't dodge the limit.
**Consequences:** Same name on a new IP gets a fresh quota (accepted: it's a soft limit). **Requires the real client IP** — see D-010.

---

## D-005 · Human input via clickable SVG in `gr.HTML` — 2026-10-02
**Context:** Human-vs-AI needs cell clicks. The existing board is an SVG string inside `gr.HTML`.
**Options:**
1. 3×3 grid of `gr.Button` — reliable, but a second board next to the styled one, or a restyle of the whole arena.
2. Dropdown / textbox for the cell number — trivial, poor UX.
3. **Gradio 6 `gr.HTML(js_on_load=…)` + `trigger('click', {cell})`** — clicks land on the existing board.
**Decision:** Option 3. Invisible `rect.hit[data-cell]` over empty cells, one delegated listener on the component root.
**Why:** Keeps one board and the existing look; delegation survives re-renders; this API is verified in the pinned Gradio 6.28 (`gr.HTML.__init__` has `js_on_load`, `EventData.__getattr__` exposes payload keys).
**Consequences:** Tied to Gradio ≥ 6's `gr.HTML` API — if Gradio is downgraded, fall back to option 1. The server re-validates every move.

## D-006 · Human games share the AI-vs-AI rate limit — 2026-10-02
**Context:** Should playing yourself be free?
**Decision:** Yes, it counts: 1 human game = 1 game toward `MAX_GAMES`.
**Why:** A human game makes ~4–5 model calls, the same cost as an AI-vs-AI match (~4–5 calls per side). The limit exists to cap spend, not to cap fun.
**Consequences:** Abandoned/errored games still count; they're logged with `winner` = `abandoned`/`error` so that's auditable.

## D-007 · Per-session `gr.State` for the human game, not DynamoDB — 2026-10-02
**Context:** A human game spans many events.
**Decision:** Keep the live game in `gr.State`; write to DynamoDB once when it ends (or is abandoned).
**Why:** No extra writes per move, no new table, and nothing for the existing AI-vs-AI path to change. A refresh = abandoned game, which is fine for tic-tac-toe.
**Consequences:** Games don't survive a page reload or server restart.

## D-008 · Additive change only: `mode` field with a default — 2026-10-02
**Context:** "Keep the existing feature intact."
**Decision:** `db.log_game(..., mode="ai_vs_ai")` keyword with a default; `view()` gains optional `label`/`clickable` args with defaults; `play()` is untouched.
**Why:** Every existing caller and every existing DynamoDB row stays valid; the AI-vs-AI code path is byte-identical in behaviour.
**Consequences:** Old rows lack `mode` — readers must treat a missing value as `ai_vs_ai`.

## D-009 · Human handlers get `concurrency_limit=8` — 2026-10-02
**Context:** Gradio's default is 1 concurrent run per listener *globally*. One click waits on a model call (0.5–5 s).
**Decision:** `HUMAN_CONCURRENCY` env var, default 8, on `start_human` and `human_move`.
**Why:** With the default, one player's slow model would freeze every other player's board.
**Consequences:** AI-vs-AI still runs one match at a time (pre-existing; deliberately not changed here). Raise both if traffic grows.

---

## D-010 · nginx in front, app bound to 127.0.0.1, `X-Forwarded-For $remote_addr` — 2026-10-02
**Context:** Rate limiting uses `gr.Request.client.host`. Behind any proxy that becomes `127.0.0.1` for everyone → all visitors share one quota.
**Decision:** nginx sends `X-Forwarded-For $remote_addr`; uvicorn (inside Gradio) trusts that header only from `127.0.0.1` (its default `FORWARDED_ALLOW_IPS`); the app binds to `127.0.0.1` so nobody can bypass nginx.
**Why:** Verified in the installed uvicorn: `proxy_headers=True` and `forwarded_allow_ips` defaults to `127.0.0.1,::1`. `$remote_addr` (not `$proxy_add_x_forwarded_for`) prevents clients from injecting a fake IP.
**Consequences:** Also gives HTTPS, and `proxy_buffering off` keeps Gradio's server-sent-event move stream live.

## D-011 · DuckDNS updated by a systemd timer — 2026-10-02
**Context:** EC2 public IPs change on every stop/start.
**Decision:** `duckdns.timer` every 5 min + 30 s after boot, calling DuckDNS with `ip=` empty (DuckDNS uses the caller's IP).
**Why:** systemd timers exist on both Ubuntu and Amazon Linux 2023 (AL2023 has no cron by default); runs after boot without extra setup; logs go to journald. The token lives in `/etc/ttt-arena/duckdns.env` (root, 600), not in a crontab.
**Consequences:** Up to ~5 min of stale DNS after an IP change. An Elastic IP would remove that but costs money when idle.

## D-012 · Push-based deploy over SSH (tar), no git on the server — 2026-10-02
**Context:** Need a repeatable deploy for one instance.
**Decision:** `deploy.sh` streams `src/ requirements.txt deploy/` as a tarball over SSH; `.env` is sent separately and only on request.
**Why:** No GitHub credentials on the server, no rsync dependency, works with an unpushed local branch, and secrets never pass through git.
**Consequences:** Deleted files aren't removed on the server (harmless for this layout). No CI/CD — fine for a single-person project; revisit with GitHub Actions + SSM if more people deploy.

## D-013 · Prefer an EC2 IAM role over AWS keys in `.env` — 2026-10-02
**Context:** `.env` currently holds `AWS_ACCESS_KEY_ID`/`SECRET`.
**Decision:** Ship `deploy/iam-policy.json` (only the 7 DynamoDB actions the code uses, scoped to the two tables) and recommend attaching it as an instance role, then deleting the keys from the server `.env`.
**Why:** No long-lived secret on disk; credentials rotate automatically.
**Consequences:** Not enforced by the scripts — existing key-based setups keep working.

## D-014 · Certbot in its own venv — 2026-10-02
**Context:** Certbot packaging differs (apt vs. not in AL2023 default repos; snap not on AL).
**Decision:** `python -m venv /opt/certbot && pip install certbot certbot-nginx` — the method EFF documents for pip installs; renewal via `certbot-renew.timer`.
**Why:** Identical on both distros.
**Consequences:** Certbot isn't upgraded by the OS; re-running `setup` won't upgrade it either (delete `/opt/certbot` to force).

## D-015 · AWS resources created by hand, not with Terraform/CDK — 2026-10-02
**Context:** The deploy scripts could also create the instance, security group and IAM role.
**Decision:** Keep those as one-time console steps (documented in `DEPLOYMENT.md` §0); scripts only configure an existing instance.
**Why:** It's one box created once. IaC would add a tool, state files and AWS admin credentials on the laptop for little gain.
**Consequences:** Rebuilding from scratch takes ~10 manual minutes. Revisit if a second environment (staging) is needed.
