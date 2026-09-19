# app.py — Tic-Tac-Toe Model Arena (name gate, rate limit, DB logging)
import os, json, time, html, random
import gradio as gr
from openai import OpenAI
from dotenv import load_dotenv
import db   # our DynamoDB layer

load_dotenv(override=True)
db.ensure_tables()   # make sure tables exist on startup

EMPTY, X, O = 0, 1, 2
SYMBOL = {EMPTY: ".", X: "X", O: "O"}
LINES = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]

def render(board):
    return "\n".join(" ".join(SYMBOL[board[i]] for i in range(r, r+3)) for r in range(0,9,3))
def legal_moves(board):
    return [i for i, v in enumerate(board) if v == EMPTY]
def is_legal(board, cell):
    return isinstance(cell, int) and 0 <= cell <= 8 and board[cell] == EMPTY
def winner(board):
    for a,b,c in LINES:
        if board[a] == board[b] == board[c] != EMPTY:
            return board[a]
    return None
def is_draw(board):
    return not legal_moves(board) and winner(board) is None
def apply_move(board, cell, player):
    if is_legal(board, cell):
        board[cell] = X if player == "X" else O
        return True
    return False
def build_prompt(board, player):
    return f"""You are playing tic-tac-toe. You are '{player}'.
The board has 9 cells numbered 0-8 (top-left is 0, bottom-right is 8).
Current board:
{render(board)}
Available cells: {legal_moves(board)}
Reply with ONLY JSON: {{"cell": <number>, "reasoning": "<short explanation>"}}"""

# ── model registry — small, cheap models only ────────────────────────────────
MODELS = {}
if os.getenv("OPENAI_API_KEY"):
    _oa = OpenAI()
    MODELS["gpt-4.1-nano (OpenAI)"] = (_oa, "gpt-4.1-nano")
    MODELS["gpt-4o-mini (OpenAI)"]  = (_oa, "gpt-4o-mini")
if os.getenv("GROQ_API_KEY"):
    _gq = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
    MODELS["gpt-oss-20b (Groq)"]    = (_gq, "openai/gpt-oss-20b")
    MODELS["gpt-oss-120b (Groq)"]   = (_gq, "openai/gpt-oss-120b")
if not MODELS:
    raise SystemExit("No API keys found in .env — add at least OPENAI_API_KEY.")

def get_move_record(client, model, board, player, max_retries=3):
    illegal, latency_ms, tokens = 0, 0, 0
    for _ in range(max_retries + 1):
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_prompt(board, player)}],
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.time() - t0) * 1000)
        tokens = resp.usage.total_tokens if resp.usage else 0
        try:
            data = json.loads(resp.choices[0].message.content)
            cell, reasoning = int(data["cell"]), data.get("reasoning", "")
        except Exception:
            cell, reasoning = None, "(unparseable response)"
        if is_legal(board, cell):
            return {"cell": cell, "reasoning": reasoning, "latency": latency_ms,
                    "tokens": tokens, "illegal": illegal}
        illegal += 1
    cell = random.choice(legal_moves(board))
    return {"cell": cell, "reasoning": "(random fallback after illegal attempts)",
            "latency": latency_ms, "tokens": tokens, "illegal": illegal}

def cell_label(i):
    return "abc"[i % 3] + str(i // 3 + 1)

# ── SVG + view rendering (same as before) ────────────────────────────────────
def board_svg(board, last=None):
    p = []
    for k in (1, 2):
        p.append(f'<line x1="{k*100}" y1="6" x2="{k*100}" y2="294" class="grid"/>')
        p.append(f'<line x1="6" y1="{k*100}" x2="294" y2="{k*100}" class="grid"/>')
    for i in range(9):
        x, y = (i % 3)*100, (i // 3)*100
        if i == last:
            p.append(f'<rect x="{x+5}" y="{y+5}" width="90" height="90" rx="6" class="hl"/>')
        if board[i] == X:
            p.append(f'<line x1="{x+30}" y1="{y+30}" x2="{x+70}" y2="{y+70}" class="xg"/>')
            p.append(f'<line x1="{x+70}" y1="{y+30}" x2="{x+30}" y2="{y+70}" class="xg"/>')
        elif board[i] == O:
            p.append(f'<circle cx="{x+50}" cy="{y+50}" r="22" class="og"/>')
    return f'<svg viewBox="0 0 300 300" class="board">{"".join(p)}</svg>'

def panel(side, name, s, active):
    color = "x" if side == "X" else "o"
    cls = f"panel {color}" + (" active" if active else "")
    return f"""<div class="{cls}">
      <div class="phead"><span class="mark {color}">{side}</span>
        <div><div class="mname {color}">{html.escape(name)}</div><div class="elo {color}">elo —</div></div></div>
      <div class="stats">
        <div class="stat"><div class="lbl {color}">LATENCY</div><div class="val {color}">{s['latency']}ms</div></div>
        <div class="stat"><div class="lbl {color}">TOKENS</div><div class="val {color}">{s['tokens']:,}</div></div>
        <div class="stat"><div class="lbl {color}">ILLEGAL</div><div class="val {color}">{s['illegal']}</div></div>
      </div>
      <div class="reason"><div class="lbl {color}">CURRENT REASONING</div>
        <div class="rtext {color}">{html.escape(s['reasoning'])}</div></div>
    </div>"""

def log_html(log):
    if not log:
        return '<div class="logempty">Moves will appear here…</div>'
    rows = []
    for n, side, cl, reason in log:
        color = "x" if side == "X" else "o"
        rows.append(f'<div class="logrow {color}"><span class="lnum">{n}.</span>'
                    f'<span class="lside {color}">{side} {cl}</span>'
                    f'<span class="lreason">{html.escape(reason)}</span></div>')
    return "".join(rows)

def view(board, last, stats, names, current, status, elapsed, result, log):
    banner = f'<div class="result">{html.escape(result)}</div>' if result else ""
    dot = "live" if not result else "done"
    return f"""<style>{CSS}</style>
    <div id="arena">
      <div class="topbar">
        <div class="left"><span class="dot {dot}"></span> {'LIVE' if not result else 'FINAL'} · single match</div>
        <div class="right">{elapsed:04.1f}s elapsed</div>
      </div>
      <div class="main">
        {panel("X", names["X"], stats["X"], current == "X")}
        <div class="center">
          {board_svg(board, last)}
          <div class="status">{html.escape(status)}</div>
          {banner}
        </div>
        {panel("O", names["O"], stats["O"], current == "O")}
      </div>
      <div class="logwrap"><div class="logtitle">SESSION LOG · reasoning per move</div>
        <div class="log">{log_html(log)}</div></div>
    </div>"""

def fresh():
    return {"X": {"latency":0,"tokens":0,"illegal":0,"reasoning":"—"},
            "O": {"latency":0,"tokens":0,"illegal":0,"reasoning":"—"}}

# ── name gate: validate name, check rate, reveal arena ───────────────────────
def enter(name, request: gr.Request):
    name = (name or "").strip()
    if not name:
        return (gr.update(), gr.update(visible=True),
                gr.update(value="Please enter your name."), None, None)
    ip = request.client.host if request else "unknown"          # Gradio gives us the IP
    user_id = db.make_user_id(name, ip)
    allowed, played = db.check_rate(user_id)
    if not allowed:
        msg = f"Limit reached ({played}/{db.MAX_GAMES}). Try again after {db.WINDOW_HOURS}h."
        return (gr.update(), gr.update(visible=True),
                gr.update(value=msg), None, None)
    # allowed → hide gate, show arena, stash identity in state
    remaining = db.MAX_GAMES - played
    return (gr.update(visible=False), gr.update(visible=False),
            gr.update(value=f"Welcome {name} · {remaining} games left"),
            (name, ip, user_id),
            gr.update(visible=True))
            
def refresh_status(identity):
    if not identity:
        return gr.update()
    name, ip, user_id = identity
    _, played = db.check_rate(user_id)
    remaining = max(0, db.MAX_GAMES - played)
    return gr.update(value=f"Welcome {name} · {remaining} games left")

# ── play one match: re-check rate, stream game, log result ───────────────────
def play(identity, x_choice, o_choice):
    if not identity:
        yield view([EMPTY]*9, None, fresh(), {"X":x_choice,"O":o_choice},
                   None, "Session error — reload.", 0.0, "Error", [])
        return
    name, ip, user_id = identity
    allowed, played = db.check_rate(user_id)
    if not allowed:
        yield view([EMPTY]*9, None, fresh(), {"X":x_choice,"O":o_choice},
                   None, f"Limit reached ({played}/{db.MAX_GAMES}).", 0.0, "Blocked", [])
        return
    db.increment_games(user_id, name, ip)   # count this game up front

    board = [EMPTY]*9
    stats, log = fresh(), []
    names = {"X": x_choice, "O": o_choice}
    clients = {"X": MODELS[x_choice], "O": MODELS[o_choice]}
    start, player, last, n = time.time(), "X", None, 0
    result_side = "draw"

    while True:
        yield view(board, last, stats, names, player,
                   f"{names[player]} thinking…", time.time()-start, None, log)
        client, model = clients[player]
        rec = get_move_record(client, model, board, player)
        s = stats[player]
        s.update(latency=rec["latency"], tokens=s["tokens"]+rec["tokens"],
                 illegal=s["illegal"]+rec["illegal"], reasoning=rec["reasoning"])
        apply_move(board, rec["cell"], player)
        last, n = rec["cell"], n+1
        log.append((n, player, cell_label(rec["cell"]), rec["reasoning"]))

        w = winner(board)
        if w is not None:
            result_side = player
            res = f"{player} · {names[player]} wins!"
            yield view(board, last, stats, names, None, res, time.time()-start, res, log)
            break
        if is_draw(board):
            yield view(board, last, stats, names, None, "Draw", time.time()-start, "Draw", log)
            break
        player = "O" if player == "X" else "X"
        yield view(board, last, stats, names, player,
                   f"{names[player]} to move", time.time()-start, None, log)

    # log the finished game (reasoning_log as list of dicts for DynamoDB)
    db.log_game(user_id, name, ip, x_choice, o_choice, result_side,
                [{"n": n_, "side": sd, "cell": cl, "reasoning": rs} for n_, sd, cl, rs in log])

CORAL, TEAL = "#e2775a", "#3fb6b6"
CSS = f"""
#arena{{font-family:ui-monospace,Menlo,Consolas,monospace;background:#17110d;
  border:1px solid #3a2c22;border-radius:12px;padding:20px;color:#e8ddd2;width:100%;box-sizing:border-box}}
#arena .topbar{{display:flex;justify-content:space-between;font-size:13px;color:#8a7a6c;letter-spacing:.08em;margin-bottom:18px}}
#arena .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
#arena .dot.live{{background:{CORAL};box-shadow:0 0 8px {CORAL}}}
#arena .dot.done{{background:{TEAL}}}
#arena .main{{display:flex;gap:24px;align-items:stretch;justify-content:center}}
#arena .center{{flex:0 0 auto;text-align:center;display:flex;flex-direction:column;justify-content:center}}
#arena .panel{{flex:1;background:#1f1712;border:1px solid #3a2c22;border-radius:10px;padding:16px;min-width:0}}
#arena .panel.x.active{{border-color:{CORAL};box-shadow:0 0 0 1px {CORAL}}}
#arena .panel.o.active{{border-color:{TEAL};box-shadow:0 0 0 1px {TEAL}}}
#arena .phead{{display:flex;gap:12px;align-items:center;margin-bottom:14px}}
#arena .mark{{font-size:26px;font-weight:700}}
#arena .x{{color:{CORAL}}} #arena .o{{color:{TEAL}}}
#arena .mname{{font-weight:600;font-size:15px}} #arena .elo{{font-size:11px;opacity:.7}}
#arena .stats{{display:flex;gap:10px;margin-bottom:14px}}
#arena .stat{{flex:1;background:#17110d;border:1px solid #3a2c22;border-radius:6px;padding:8px 10px}}
#arena .lbl{{font-size:9px;letter-spacing:.12em;opacity:.75}} #arena .val{{font-size:15px;margin-top:3px}}
#arena .reason{{background:#17110d;border:1px solid #3a2c22;border-radius:6px;padding:10px}}
#arena .rtext{{font-size:13px;line-height:1.5;margin-top:5px}}
#arena .board{{width:300px;height:300px}}
#arena .grid{{stroke:#4a382c;stroke-width:2}}
#arena .xg{{stroke:{CORAL};stroke-width:8;stroke-linecap:round}}
#arena .og{{fill:none;stroke:{TEAL};stroke-width:8}}
#arena .hl{{fill:#4a2f1e}}
#arena .status{{margin-top:12px;font-size:13px;color:#8a7a6c}}
#arena .result{{margin-top:10px;font-size:17px;font-weight:700}}
#arena .logwrap{{margin-top:20px;border-top:1px solid #3a2c22;padding-top:14px}}
#arena .logtitle{{font-size:11px;letter-spacing:.12em;color:#8a7a6c;margin-bottom:10px}}
#arena .log{{display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto}}
#arena .logrow{{display:flex;gap:10px;font-size:13px;padding:6px 8px;border-radius:6px;background:#1f1712;align-items:baseline}}
#arena .lnum{{color:#8a7a6c;min-width:24px}} #arena .lside{{font-weight:700;min-width:42px}}
#arena .lreason{{color:#cbbdae;line-height:1.4}} #arena .logempty{{color:#8a7a6c;font-size:13px;font-style:italic}}
"""

# full-screen: kill Gradio's default max-width on the whole container
GLOBAL_CSS = ".gradio-container{max-width:100% !important;padding:16px 24px !important}"

choices = list(MODELS)
x_def = choices[0]
o_def = choices[1] if len(choices) > 1 else choices[0]

with gr.Blocks(theme=gr.themes.Base(
        primary_hue="orange", neutral_hue="stone").set(
        body_background_fill="#17110d",
        background_fill_primary="#1f1712",
        block_background_fill="#1f1712",
        body_text_color="#e8ddd2",
        input_background_fill="#17110d",
    ), title="TTT Model Arena", fill_width=True, css=GLOBAL_CSS) as demo:
    gr.Markdown("### Tic-Tac-Toe Model Arena")
    identity = gr.State(None)   # holds (name, ip, user_id) after gate

    # ── Screen 1: name gate ──
    with gr.Group(visible=True) as gate:
        name_in = gr.Textbox(label="Enter your name to start", placeholder="e.g. Arya")
        enter_btn = gr.Button("Continue ▶", variant="primary")
    status_md = gr.Markdown("")

    # ── Screen 2: arena (hidden until gate passes) ──
    with gr.Group(visible=False) as arena:
        with gr.Row():
            x_dd = gr.Dropdown(choices, value=x_def, label="Player X (coral)")
            o_dd = gr.Dropdown(choices, value=o_def, label="Player O (teal)")
        play_btn = gr.Button("▶ Play match", variant="primary")
        out = gr.HTML(view([EMPTY]*9, None, fresh(), {"X":x_def,"O":o_def},
                           None, "Press play to start", 0.0, None, []))

    enter_btn.click(enter, [name_in],
                    [gate, name_in, status_md, identity, arena])
    play_btn.click(play, [identity, x_dd, o_dd], out).then(
    refresh_status, [identity], status_md)

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        theme=gr.themes.Base(
            primary_hue="orange", neutral_hue="stone").set(
            body_background_fill="#17110d",
            background_fill_primary="#1f1712",
            block_background_fill="#1f1712",
            body_text_color="#e8ddd2",
            input_background_fill="#17110d",
        ),
        css=GLOBAL_CSS,
    )