# bot_friend/discord_bot.py
import discord
import asyncio
from discord.ext import commands
from .ratelimit import RateLimiter
from .handlers.persistence import persist_message
from .handlers.interaction import InteractionHandler
from .config import get_settings
from .db import init_db
from .services.reply_service import ReplyService
from .web_server import start_web_server

def build_bot(handler: InteractionHandler, message_window: int, message_limit: int) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    limiter = RateLimiter(message_window, message_limit)

    @bot.event
    async def on_ready():
        print(f"✅ Logged in as {bot.user}")

    @bot.event
    async def on_message(message: discord.Message):
        if message.author == bot.user:
            return

        # ذخیرهٔ همهٔ پیام‌ها
        try:
            await persist_message(handler.db_path, message, is_bot_reply=False)
        except Exception as e:
            print(f"[persist] {e}")

        # Rate limit
        if not limiter.allow(message.author.id):
            await message.reply("خیلی داری حرف می‌زنی 🤐", mention_author=False)
            return

        mentioned = bot.user.mentioned_in(message)
        replied_to_bot = (
            message.reference is not None and
            isinstance(message.reference.resolved, discord.Message) and
            message.reference.resolved.author == bot.user
        )

        if mentioned or replied_to_bot:
            async with message.channel.typing():
                await handler.handle_reply_or_mention(message)

        await bot.process_commands(message)

    @bot.command()
    async def hello(ctx):
        await ctx.send("سلام! من اوستینا هستم 😋🌸")

    return bot

def _build():
    s = get_settings()
    init_db(s.db_path)
    reply_service = ReplyService(api_key=s.openai_api_key, model=s.model)
    from .handlers.interaction import InteractionHandler
    handler = InteractionHandler(db_path=s.db_path, reply_service=reply_service)
    bot = build_bot(handler, s.msg_window_seconds, s.msg_limit)
    return s, bot

async def run():
    s, bot = _build()
    web_task = asyncio.create_task(start_web_server(s.web_port))

    async def run_bot():
        while True:
            try:
                await bot.start(s.token)
            except Exception as e:
                print(f"⚠️ Bot error: {e}. retrying in 10s…")
                await asyncio.sleep(10)

    bot_task = asyncio.create_task(run_bot())
    await asyncio.gather(web_task, bot_task)
