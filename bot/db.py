# bot_friend/db.py
import os, sqlite3
from typing import Iterator
from contextlib import contextmanager

def _ensure_dir(db_path: str):
    d = os.path.dirname(db_path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

@contextmanager
def get_conn(db_path: str) -> Iterator[sqlite3.Connection]:
    _ensure_dir(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()

def init_db(db_path: str):
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          discord_user_id TEXT NOT NULL,
          guild_id TEXT NOT NULL,
          UNIQUE(discord_user_id, guild_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY,
          guild_id TEXT NOT NULL,
          channel_id TEXT NOT NULL,
          message_id TEXT NOT NULL UNIQUE,
          author_user_id INTEGER NOT NULL,
          content TEXT NOT NULL,
          replied_to_message_id TEXT,
          replied_to_author_user_id INTEGER,
          is_bot_reply INTEGER DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(author_user_id) REFERENCES users(id),
          FOREIGN KEY(replied_to_author_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS ix_msg_guild_channel_time
          ON messages(guild_id, channel_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_msg_author_time
          ON messages(author_user_id, created_at DESC);
        """)
        conn.commit()
