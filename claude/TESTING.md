# Testing

## Offline tests (free, no AWS, no API calls)

```bash
./venv/bin/python tests/test_human_mode.py
```

`tests/test_human_mode.py` swaps `db` for an in-memory module and replaces
`get_move_record` with a deterministic "lowest free cell" player, then checks:

- a full human win as X (logged as `human_vs_ai`, human stored as `human:<name>`, board locked after)
- human as O → model opens; occupied-cell / malformed / no-game clicks are ignored
- switching mode mid-game logs the game as `abandoned`
- rate limit blocks a new human game
- AI-vs-AI still runs and logs as `ai_vs_ai`

## Manual browser check (what was done on 2026-10-02)

Run the same stubs as a server, open http://127.0.0.1:7861, and click through:

```python
# save as /tmp/serve_stub.py, run with ./venv/bin/python /tmp/serve_stub.py
import sys, time; sys.path.insert(0, "tests")
import test_human_mode as t                 # installs the fake db + fake model
_m = t.app.get_move_record
t.app.get_move_record = lambda *a, **k: (time.sleep(1), _m(*a, **k))[1]   # visible "thinking"
t.app.demo.launch(server_name="127.0.0.1", server_port=7861,
                  theme=t.app.THEME, css=t.app.GLOBAL_CSS)
```

Verified: name gate → mode radio → Start as X → click centre → "thinking…" →
model reply → "Your move"; Start as O → model opens; switch back to AI vs AI
→ full match plays; "games left" counter decrements for both modes.

## Deploy scripts

- `bash -n deploy/*.sh` — syntax (done).
- nginx template: `nginx -t` inside the `nginx:stable` container was **not**
  run (Docker daemon was off); `server_setup.sh` runs `nginx -t` before
  restarting nginx, so a bad config stops the setup instead of taking the site down.
- The scripts have not been run against a real instance from this repo yet;
  first `./deploy/deploy.sh setup` is the real test — read its output.
