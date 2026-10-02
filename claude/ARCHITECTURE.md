# Architecture

## Files

```
src/app.py      Gradio UI + game engine + model calls (single file on purpose — see D-002)
src/db.py       DynamoDB layer: table bootstrap, rate limiting, game logging
requirements.txt
deploy/         deployment scripts (see DEPLOYMENT.md)
claude/         this documentation
.env            secrets — NOT in git (API keys, AWS creds, limits)
```

## Runtime picture

```
 Browser ──HTTPS──▶ nginx :443 ──▶ 127.0.0.1:7860  Gradio (app.py, systemd: ttt-arena)
                                        │
                                        ├──▶ OpenAI API   (gpt-4.1-nano, gpt-4o-mini)
                                        ├──▶ Groq API     (gpt-oss-20b, gpt-oss-120b)
                                        └──▶ DynamoDB     (ttt_users, ttt_games)

 duckdns.timer (every 5 min) ──▶ duckdns.org  keeps <sub>.duckdns.org → EC2 public IP
 certbot-renew.timer (2×/day) ──▶ Let's Encrypt
```

## Screens & flow

1. **Name gate** — `enter()` builds `user_id = "<lowercased name>#<ip>"` and calls
   `db.check_rate`. If allowed, the arena is revealed and `(name, ip, user_id)`
   is kept in `gr.State` (`identity`).
2. **Arena** — a *Mode* radio switches between two control groups that share
   one board (`out`, a `gr.HTML`):
   - **AI vs AI** (`play()`): one long generator streams the whole game.
   - **Human vs AI** (`start_human()` + `human_move()`): one event per move;
     the game lives in `gr.State` (`hgame`). Details: [HUMAN_VS_AI.md](HUMAN_VS_AI.md).
3. After a game *starts*, `refresh_status` updates "N games left".

## Model calls

`get_move_record()` sends the board as text and asks for JSON
`{"cell": n, "reasoning": "..."}` with `response_format=json_object`.
Illegal/unparseable answers are retried up to 3 times; after that a random
legal move is played so a game can never hang on a misbehaving model. Latency,
tokens and the illegal-move count are shown live in each player's panel.

Models are registered only if their API key exists (`MODELS` dict), so the
dropdowns never offer a model that can't be called.

## DynamoDB schema

Both tables: on-demand billing, TTL on `expires_at`, auto-created at startup by
`db.ensure_tables()`.

**`ttt_users`** — PK `user_id` (`name#ip`)

| attr | meaning |
|---|---|
| `games_played` | games started in the current window |
| `window_start` | ISO time the window opened |
| `expires_at` | epoch; window end (`RATE_WINDOW_HOURS`, default 10h). TTL deletes the row after |

**`ttt_games`** — PK `game_id` (uuid4)

| attr | meaning |
|---|---|
| `user_id`, `name`, `ip` | who triggered the game |
| `mode` | `ai_vs_ai` or `human_vs_ai` (added 2026-10-02; old rows have no `mode` → treat as `ai_vs_ai`) |
| `x_model`, `o_model` | model display names; a human side is stored as `human:<name>` |
| `winner` | `X` / `O` / `draw`; human games may also be `abandoned` or `error` |
| `reasoning_log` | list of `{n, side, cell, reasoning}`; human moves have reasoning `(human move)` |
| `created_at` / `expires_at` | ISO time / epoch TTL (`LOG_RETENTION_DAYS`, default 15) |

## Configuration (env vars, read from `.env` and systemd)

| var | default | used by |
|---|---|---|
| `OPENAI_API_KEY`, `GROQ_API_KEY` | — | which models are offered |
| `AWS_REGION` | `us-east-1` | DynamoDB |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | optional; prefer an EC2 instance role (D-013) |
| `MAX_GAMES` | 5 | games per window per name+IP |
| `RATE_WINDOW_HOURS` | 10 | window length |
| `LOG_RETENTION_DAYS` | 15 | game log TTL |
| `HOST` / `PORT` | `0.0.0.0` / 7860 | bind address (systemd sets `127.0.0.1` behind nginx) |
| `HUMAN_CONCURRENCY` | 8 | parallel Human-vs-AI events Gradio will run |
