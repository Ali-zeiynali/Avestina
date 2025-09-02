# bot_friend/repositories/users_repo.py
from ..db import get_conn

def upsert_user(db_path: str, discord_user_id: str, guild_id: str) -> int:
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE discord_user_id=? AND guild_id=?", (discord_user_id, guild_id))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO users(discord_user_id,guild_id) VALUES(?,?)", (discord_user_id, guild_id))
        conn.commit()
        return cur.lastrowid
