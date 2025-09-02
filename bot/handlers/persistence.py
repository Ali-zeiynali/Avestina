# bot_friend/handlers/persistence.py
import asyncio
import discord
from ..repositories.users_repo import upsert_user
from ..repositories.messages_repo import add_message_row

async def persist_message(db_path: str, message: discord.Message, is_bot_reply: bool = False):
    gid = str(message.guild.id) if message.guild else "dm"
    cid = str(message.channel.id)
    mid = str(message.id)
    author_uid = upsert_user(db_path, str(message.author.id), gid)

    replied_to_mid = None
    replied_to_author_id = None
    if message.reference:
        replied_to_mid = str(message.reference.message_id) if message.reference.message_id else None
        if isinstance(message.reference.resolved, discord.Message):
            replied_to_author_id = upsert_user(db_path, str(message.reference.resolved.author.id), gid)

    await asyncio.to_thread(
        add_message_row,
        db_path,
        gid, cid, mid, author_uid, message.content,
        replied_to_mid, replied_to_author_id,
        1 if is_bot_reply else 0
    )
