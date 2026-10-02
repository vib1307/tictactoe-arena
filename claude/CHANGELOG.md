# Changelog

## 2026-10-02 — Human vs AI mode + deployment automation

**Added**
- 🧑 **Human vs AI** mode: pick X or O and an opponent model, click cells on the
  arena board to play. AI vs AI mode unchanged and still the default. (`src/app.py`)
- `mode` field on `ttt_games` rows (`ai_vs_ai` / `human_vs_ai`); human games can
  end `abandoned` or `error`. (`src/db.py`)
- `HOST`, `PORT`, `HUMAN_CONCURRENCY` env vars (defaults keep old behaviour).
- `deploy/`: `deploy.sh` (setup/update/env/status/logs/restart/ssh),
  `server_setup.sh` (systemd, DuckDNS timer, nginx, Let's Encrypt),
  nginx template, least-privilege IAM policy, config example.
- `tests/test_human_mode.py` — offline tests with stubbed DB/model.
- `claude/` — this documentation folder.

**Changed**
- Theme defined once (`THEME`) and shared by `Blocks()` and `launch()`; radio
  labels made readable on the dark background.
- `.gitignore`: `deploy/deploy.config` (holds the DuckDNS token).

**Fixed during development** (never shipped)
- `winner()` returns ints (`X`=1/`O`=2); the first draft compared it to the
  string `"X"`, so a human win wasn't detected. Caught by the offline test.

## 2026-09-19 — Initial arena *(reconstructed from git)*
- AI vs AI arena with live SVG board, per-model latency/tokens/illegal stats,
  reasoning log.
- Name gate + DynamoDB rate limit (5 games / 10 h per name+IP) and 15-day game logs.
- Models: gpt-4.1-nano, gpt-4o-mini (OpenAI); gpt-oss-20b/120b (Groq).
