# db.py — DynamoDB layer for rate-limiting and game logs
import os, time, uuid
import boto3
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

MAX_GAMES      = int(os.getenv("MAX_GAMES", 5))
WINDOW_HOURS   = int(os.getenv("RATE_WINDOW_HOURS", 10))
RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", 15))

_ddb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
users_table = _ddb.Table("ttt_users")
games_table = _ddb.Table("ttt_games")

# ── Table auto-creation (runs once at startup; no-op if tables already exist) ──
_ddb_client = boto3.client("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))

def _table_exists(name):
    return name in _ddb_client.list_tables()["TableNames"]

def _create_table(name, pk):
    _ddb_client.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    _ddb_client.get_waiter("table_exists").wait(TableName=name)
    _ddb_client.update_time_to_live(
        TableName=name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
    )

def ensure_tables():
    if not _table_exists("ttt_users"):
        _create_table("ttt_users", "user_id")
    if not _table_exists("ttt_games"):
        _create_table("ttt_games", "game_id")

def _now_epoch():
    return int(time.time())

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def make_user_id(name, ip):
    # Rate limit is keyed on a "name#ip" combo. Lowercase and strip the name
    # so that "Arya", " arya " etc. all map to the same user.
    return f"{name.strip().lower()}#{ip}"

# ── 1. Rate check — is the user still allowed to play? ────────────────────────
def check_rate(user_id):
    resp = users_table.get_item(Key={"user_id": user_id})
    if "Item" not in resp:
        return True, 0                         # New user, no games played yet.
    item = resp["Item"]
    if int(item["expires_at"]) < _now_epoch():
        return True, 0                         # 10h window has passed → reset.
    played = int(item["games_played"])
    if played >= MAX_GAMES:
        return False, played                   # Limit reached → block.
    return True, played                        # Allowed; this many played so far.

# ── 2. Increment the game count (called when a game starts) ───────────────────
def increment_games(user_id, name, ip):
    resp = users_table.get_item(Key={"user_id": user_id})
    expired = ("Item" not in resp) or (int(resp["Item"]["expires_at"]) < _now_epoch())
    if expired:
        # Start a fresh window: count = 1, expiry = now + 10h.
        users_table.put_item(Item={
            "user_id": user_id, "name": name, "ip": ip,
            "games_played": 1,
            "window_start": _now_iso(),
            "expires_at": _now_epoch() + WINDOW_HOURS * 3600,
        })
    else:
        # Window is still active: bump the counter only, leave expiry untouched
        # (resetting it would slide the window forward on every game).
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET games_played = games_played + :one",
            ExpressionAttributeValues={":one": 1},
        )

# ── 3. Store the full game record (called when a game ends) ───────────────────
def log_game(user_id, name, ip, x_model, o_model, winner, reasoning_log):
    games_table.put_item(Item={
        "game_id": str(uuid.uuid4()),          # Unique id for this game.
        "user_id": user_id, "name": name, "ip": ip,
        "x_model": x_model, "o_model": o_model,
        "winner": winner,                      # "X" / "O" / "draw"
        "reasoning_log": reasoning_log,        # List of {n, side, cell, reasoning}.
        "created_at": _now_iso(),
        "expires_at": _now_epoch() + RETENTION_DAYS * 86400,   # 15-day TTL.
    })