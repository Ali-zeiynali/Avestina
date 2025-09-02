# bot_friend/repositories/messages_repo.py
from ..db import get_conn

def add_message_row(
    db_path: str,
    guild_id: str,
    channel_id: str,
    message_id: str,
    author_user_id: int,
    content: str,
    replied_to_message_id: str | None = None,
    replied_to_author_user_id: int | None = None,
    is_bot_reply: int = 0,
):
    content = (content or "").strip()
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO messages
              (guild_id, channel_id, message_id, author_user_id, content,
               replied_to_message_id, replied_to_author_user_id, is_bot_reply)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET
              content=excluded.content,
              updated_at=CURRENT_TIMESTAMP,
              replied_to_message_id=excluded.replied_to_message_id,
              replied_to_author_user_id=excluded.replied_to_author_user_id,
              is_bot_reply=excluded.is_bot_reply
        """, (
            guild_id, channel_id, message_id, author_user_id, content,
            replied_to_message_id, replied_to_author_user_id, is_bot_reply
        ))
        conn.commit()

def fetch_user_bot_history(db_path: str, guild_id: str, channel_id: str, user_internal_id: int, limit: int = 14) -> list[tuple[int, str]]:
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
           SELECT is_bot_reply, content
           FROM messages
           WHERE guild_id = ?
             AND channel_id = ?
             AND (
                  (author_user_id = ? AND is_bot_reply = 0)
                  OR
                  (is_bot_reply = 1 AND replied_to_author_user_id = ?)
             )
           ORDER BY created_at DESC
           LIMIT ?
        """, (guild_id, channel_id, user_internal_id, user_internal_id, limit))
        return cur.fetchall()
