# Human vs AI mode

Added **2026-10-02**. Requirement: *let a human play against any model,
keeping the AI-vs-AI arena exactly as it was.*

## What the player sees

1. After the name gate, a **Mode** radio: `🤖 AI vs AI` (default) / `🧑 Human vs AI`.
2. In Human mode: **Play as** X or O (X moves first) + **Opponent model** + **▶ Start game**.
3. The same arena board, panels and session log are used. On the human's turn,
   empty cells highlight on hover and are clickable. While the model thinks,
   the board is locked and the model's panel glows.
4. The human's panel shows *think time* in the LATENCY slot (tokens/illegal stay 0);
   the model's panel shows its real latency/tokens/illegal attempts/reasoning.
5. Result banner: `You win!`, `<model> wins!` or `Draw`.

## How it works

### Why not reuse `play()`?
`play()` is one generator that runs a whole game in a single event. A human
game needs to **pause for input** between moves, which a single Gradio event
can't do. So a human game is a sequence of events sharing state:

```
Start game ──▶ start_human()  ─┬─ human is X → yield "Your move"         (board clickable)
                               └─ human is O → _ai_turn() → "Your move"

click cell ──▶ human_move()   ── apply human move ─┬─ game over → log, lock board
                                                   └─ _ai_turn() ─┬─ game over → log
                                                                  └─ "Your move"
```

### State (`hgame` – one `gr.State` per browser session)
```python
{"board": [0]*9, "human": "X", "ai": "O", "model": "<display name>",
 "names": {...}, "stats": {...}, "log": [...], "last": cell, "n": moves,
 "start": t, "turn_t0": t, "turn": "X"|"O", "over": bool,
 "identity": (name, ip, user_id)}
```
`turn` + `over` are the guards: any click that arrives when it isn't the
human's turn (or no game exists) is ignored with `gr.update()` (no re-render).

### Making the board clickable
Gradio 6's `gr.HTML` accepts `js_on_load`, which can call
`trigger('click', {...})`; the Python handler receives the payload on
`gr.EventData` (`evt.cell`). We:

- render an invisible `<rect class="hit" data-cell="i">` over each **empty** cell,
  only when `clickable=True` (the human's turn);
- attach **one delegated listener on the component root** (`BOARD_JS`), so it
  keeps working after every re-render of the inner HTML;
- validate on the server anyway (`is_legal`) — the client is never trusted.

Alternatives rejected: a 3×3 grid of `gr.Button`s (second board next to the
SVG, loses the arena styling) and a cell-number dropdown (bad UX). See D-005.

### Rate limiting & logging
- A human game **counts as one game** toward `MAX_GAMES`, incremented at *Start*
  (same as AI-vs-AI) because every human game costs model API calls (D-006).
- Logged once at the end with `mode="human_vs_ai"`; the human side is stored as
  `human:<name>` in `x_model`/`o_model`.
- Starting a new game or switching mode mid-game logs the old one as
  `winner="abandoned"` (it was already counted, so keep the record).
- If the model API throws, the game ends with `winner="error"` and a message;
  this mode keeps state between events so an unhandled exception would
  otherwise leave a stuck half-game.

### Concurrency
Gradio's default is **1 concurrent run per event listener across all users**.
For AI-vs-AI that serialises matches (pre-existing behaviour, left untouched).
For human games every click waits on a model call, so one slow model would
block every other player's click; human handlers use
`concurrency_limit=HUMAN_CONCURRENCY` (default 8). Double-clicks are already
dropped by Gradio's default `trigger_mode="once"`.

## Edge cases checked

| case | behaviour |
|---|---|
| click occupied cell / bad payload | ignored, no re-render |
| click while model thinking | no hit-boxes rendered + `turn` guard |
| click after game over / in AI mode | `hgame` is over or `None` → ignored |
| rate limit hit | "Limit reached" banner, no game created, nothing counted |
| human plays O | model opens immediately after Start |
| model returns illegal moves | same retry → random fallback as AI-vs-AI |
| switch mode mid-game | old game logged `abandoned`, board reset |

## Ideas not done (yet)
- Elo per model vs humans (panel already shows `elo —` placeholder).
- Leaderboard of human win-rate per model from `ttt_games` (`mode = human_vs_ai`).
- Keyboard input (1–9) for accessibility.
