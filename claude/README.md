# `claude/` — project notes, decisions & runbooks

This folder records **what** was built, **why** it was built that way, **when** it
changed, and **how** to operate it. It is the place to look before changing
anything non-obvious. Code comments explain *how a line works*; these files
explain *why the system is shaped like this*.

| File | Read it when… |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | you're new to the code: components, data flow, DynamoDB schema |
| [HUMAN_VS_AI.md](HUMAN_VS_AI.md) | you're touching the Human-vs-AI mode (design, state machine, edge cases) |
| [DEPLOYMENT.md](DEPLOYMENT.md) | you're deploying, updating, or debugging the EC2 / DuckDNS / nginx setup |
| [DECISIONS.md](DECISIONS.md) | you're wondering "why is it done like this?" — dated decision log (ADR style) |
| [CHANGELOG.md](CHANGELOG.md) | you want to know what changed and when |
| [TESTING.md](TESTING.md) | you want to verify a change without spending API credits or touching prod DynamoDB |

## The project in one paragraph

**Tic-Tac-Toe Model Arena** is a Gradio web app where LLMs play tic-tac-toe.
Visitors enter a name (rate-limited per name+IP via DynamoDB), then either
watch **two models play each other** (the original mode) or **play against a
model themselves** (added 2026-10-02). Every finished game, including each
model's per-move reasoning, is logged to DynamoDB with a 15-day TTL. It runs
on a single EC2 instance behind nginx, with a free `*.duckdns.org` hostname
and a Let's Encrypt certificate.

## Conventions for updating this folder

- **New decision?** Append an entry to `DECISIONS.md` (never rewrite old ones —
  supersede them with a new entry that links back).
- **Shipped a change?** Add a dated line to `CHANGELOG.md`.
- Dates are absolute (`YYYY-MM-DD`), never "last week".
- Entries marked *(reconstructed)* were inferred from the code after the fact,
  not recorded at the time.
