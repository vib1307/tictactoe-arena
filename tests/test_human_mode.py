# test_human_mode.py — offline checks for both game modes.
# Stubs the DynamoDB layer and the model call, so it costs nothing and
# touches no AWS resources:   ./venv/bin/python tests/test_human_mode.py
import os, sys, types

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

# ── in-memory stand-in for db.py ─────────────────────────────────────────────
fake = types.ModuleType("db")
fake.MAX_GAMES, fake.WINDOW_HOURS = 5, 10
fake.counts, fake.logs = {}, []
fake.ensure_tables = lambda: None
fake.make_user_id = lambda n, ip: f"{n.strip().lower()}#{ip}"
fake.check_rate = lambda u: (fake.counts.get(u, 0) < fake.MAX_GAMES, fake.counts.get(u, 0))
def _inc(u, n, ip): fake.counts[u] = fake.counts.get(u, 0) + 1
fake.increment_games = _inc
fake.log_game = lambda *a, mode="ai_vs_ai": fake.logs.append((a, mode))
sys.modules["db"] = fake

os.environ.setdefault("OPENAI_API_KEY", "sk-fake")   # only needed if no .env
import app

# deterministic "model": always the lowest free cell
app.get_move_record = lambda client, model, board, player, max_retries=3: {
    "cell": app.legal_moves(board)[0], "reasoning": "lowest free cell",
    "latency": 5, "tokens": 10, "illegal": 0}

class Ev:                                   # stands in for gr.EventData
    def __init__(self, cell): self.cell = cell

def run(gen):
    *_, last = gen
    return last

IDENT = ("Arya", "1.2.3.4", "arya#1.2.3.4")
MODEL = list(app.MODELS)[0]

def test_human_x_wins():
    html, g = run(app.start_human(IDENT, "X", MODEL, None))
    assert g["turn"] == "X" and 'data-cell="4"' in html
    for c in (4, 8, 2, 6):                  # model takes 0,1,3 → X wins on 2-4-6
        html, g = run(app.human_move(g, Ev(c)))
    assert g["over"] and "You win!" in html
    assert "data-cell" not in html          # board locked after the game
    args, mode = fake.logs[-1]
    assert mode == "human_vs_ai" and args[5] == "X" and args[3] == "human:Arya"

def test_ignored_clicks():
    html, g = run(app.start_human(IDENT, "O", MODEL, None))
    assert g["board"][0] == app.X and g["turn"] == "O"      # model opened
    assert run(app.human_move(g, Ev(0)))[0] == app.gr.update()   # occupied
    assert run(app.human_move(g, Ev("x")))[0] == app.gr.update() # bad payload
    assert run(app.human_move(None, Ev(3)))[1] is None           # no game
    return g

def test_mode_switch_abandons():
    g = test_ignored_clicks()
    out = app.switch_mode(app.MODE_AI, g)
    assert out[3] is None and fake.logs[-1][0][5] == "abandoned"

def test_rate_limit():
    fake.counts[IDENT[2]] = fake.MAX_GAMES
    html, g = run(app.start_human(IDENT, "X", MODEL, None))
    assert g is None and "Limit reached" in html
    fake.counts[IDENT[2]] = 0

def test_ai_vs_ai_unchanged():
    run(app.play(IDENT, MODEL, MODEL))
    assert fake.logs[-1][1] == "ai_vs_ai"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok  ", name)
    print("ALL OK")
