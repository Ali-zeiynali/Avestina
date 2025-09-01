import sqlite3
from constants import SAFE_KEYS, SAFE_KINDS, RE_EMAIL, RE_PHONE, RE_ACCNT, BANNED_TOKENS
from config import DB_PATH


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          discord_user_id TEXT NOT NULL,
          guild_id TEXT NOT NULL,
          UNIQUE(discord_user_id, guild_id)
        );
        CREATE TABLE IF NOT EXISTS memories (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL,
          kind TEXT NOT NULL,
          value TEXT NOT NULL,
          weight REAL DEFAULT 1.0,
          source_msg_id TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mem_user_kind_value
          ON memories(user_id, kind, value);
        CREATE INDEX IF NOT EXISTS ix_mem_user_kind_time
          ON memories(user_id, kind, updated_at DESC, created_at DESC);
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL,
          content TEXT NOT NULL,
          source_msg_id TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)
        conn.commit()


def upsert_user(discord_user_id: str, guild_id: str) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE discord_user_id=? AND guild_id=?", (discord_user_id, guild_id))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO users(discord_user_id,guild_id) VALUES(?,?)", (discord_user_id, guild_id))
        conn.commit()
        return cur.lastrowid


def add_memory(user_id: int, kind: str, value: str, source_msg_id: str | None = None):
    if kind not in SAFE_KINDS:
        return
    value = (value or "").strip()
    if not value:
        return
    if RE_EMAIL.search(value) or RE_PHONE.search(value) or RE_ACCNT.search(value):
        return
    if any(tok in value for tok in BANNED_TOKENS):
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO memories(user_id,kind,value,source_msg_id)
            VALUES (?,?,?,?)
            ON CONFLICT(user_id, kind, value) DO UPDATE SET
              updated_at = CURRENT_TIMESTAMP
        """, (user_id, kind, value, source_msg_id))
        conn.commit()


def save_message(user_id: int, content: str, source_msg_id: str | None = None):
    content = (content or "").strip()
    if not content:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages(user_id,content,source_msg_id) VALUES(?,?,?)",
            (user_id, content, source_msg_id),
        )
        conn.commit()


def get_profile_snapshot(user_id: int, limit_per_kind=8) -> dict:
    profile = {k: [] for k in SAFE_KEYS}
    with get_conn() as conn:
        cur = conn.cursor()
        for k in SAFE_KEYS:
            cur.execute(
                "SELECT value FROM memories WHERE user_id=? AND kind=? "
                "ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                (user_id, k, limit_per_kind),
            )
            profile[k] = [r[0] for r in cur.fetchall()]
    return profile
