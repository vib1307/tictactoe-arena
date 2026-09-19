# import db
# print("Creating tables...")
# db.ensure_tables()
# print("Tables ready:", db._table_exists("ttt_users"), db._table_exists("ttt_games"))

import db

# rate-limit ka test — 6 baar try, 5 ke baad block hona chahiye
uid = db.make_user_id("Blocker", "9.9.9.9")
for i in range(6):
    allowed, played = db.check_rate(uid)
    print(f"attempt {i}: allowed={allowed}, played={played}")
    if allowed:
        db.increment_games(uid, "Blocker", "9.9.9.9")

# game log ka test
db.log_game(uid, "Blocker", "9.9.9.9",
            "gpt-4.1-nano", "gpt-oss-20b", "X",
            [{"n": 1, "side": "X", "cell": "b2", "reasoning": "center control"}])
print("game logged")