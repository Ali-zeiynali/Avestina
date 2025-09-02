# bot_friend/handlers/interaction.py
import discord
from ..repositories.users_repo import upsert_user
from ..repositories.messages_repo import fetch_user_bot_history
from ..services.history_service import rows_to_openai_messages
from ..services.reply_service import ReplyService
from .persistence import persist_message
from ..state import state, logger

class InteractionHandler:
    def __init__(self, db_path: str, reply_service: ReplyService):
        self.db_path = db_path
        self.reply_service = reply_service
        self._last_replies: dict[int, str] = {}

    async def handle_reply_or_mention(self, message: discord.Message):
        if isinstance(message.channel, discord.DMChannel):
            return

        gid = str(message.guild.id) if message.guild else "dm"
        cid = str(message.channel.id)
        user_internal_id = upsert_user(self.db_path, str(message.author.id), gid)

        # تاریخچهٔ کاربر↔️بات
        if state.send_history:
            rows = fetch_user_bot_history(self.db_path, gid, cid, user_internal_id, limit=14)
            history = rows_to_openai_messages(rows, latest_user_text=message.content, max_chars=3500)

            known = any(r[0] == 1 for r in rows)
            if known:
                history.insert(0, {"role": "system", "content": "این کاربر دوستت هست و قبلاً باهات صحبت کرده پس خیلی گرم و صمیمی جواب بده"})
            else:
                history.insert(0, {"role": "system", "content": "این اولین بار است که این فرد با تو حرف می‌زند؛ با کمی شک و تردید جواب بده و به راحتی صمیمی نشو"})
        else:
            history = [{"role": "user", "content": message.content}]
            known = False

        reply_text = self.reply_service.generate(history).strip()

        if self._last_replies.get(user_internal_id) == reply_text:
            return

        async with message.channel.typing():
            sent = await message.reply(reply_text, mention_author=False)

        self._last_replies[user_internal_id] = reply_text

        # جواب بات را هم ذخیره کن
        if state.store_memory:
            try:
                await persist_message(self.db_path, sent, is_bot_reply=True)
            except Exception as e:
                logger.debug(f"[persist] {e}")
