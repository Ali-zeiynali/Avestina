import asyncio
import os
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectorError, ConnectionTimeoutError

from config import TOKEN
from db import init_db, upsert_user, add_memory, get_profile_snapshot, save_message
from llm import extract_facts_from_text, generate_reply

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

MESSAGE_WINDOW = 60
MESSAGE_LIMIT = 10
_user_msg_times: dict[int, deque] = defaultdict(deque)
STORE_MESSAGES = True


async def handle_reply_or_mention(message: discord.Message, user_id: int):
    async with message.channel.typing():
        MAX_LEN = 800
        if len(message.content) <= MAX_LEN and STORE_MESSAGES:
            facts = extract_facts_from_text(message.content)
            for k, items in facts.items():
                for it in items[:5]:
                    asyncio.create_task(
                        asyncio.to_thread(add_memory, user_id, k, it, str(message.id))
                    )
        profile = get_profile_snapshot(user_id)
        reply_ctx = None
        if message.reference and message.reference.message_id:
            try:
                ref = message.reference.resolved
                if ref is None:
                    ref = await message.channel.fetch_message(message.reference.message_id)
                role = "assistant" if ref.author == bot.user else "user"
                reply_ctx = {"role": role, "content": ref.content}
            except Exception:
                pass
        reply = generate_reply(profile, message.content, replied_message=reply_ctx)
    await message.reply(reply, mention_author=False)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    uid = str(message.author.id)
    gid = str(message.guild.id) if message.guild else "dm"
    user_id = upsert_user(uid, gid)
    if STORE_MESSAGES:
        asyncio.create_task(
            asyncio.to_thread(save_message, user_id, message.content, str(message.id))
        )
    uid_int = message.author.id
    now = time.time()
    times = _user_msg_times[uid_int]
    while times and now - times[0] > MESSAGE_WINDOW:
        times.popleft()
    if len(times) >= MESSAGE_LIMIT:
        await message.reply("خیلی داری حرف می‌زنی 🤐", mention_author=False)
        return
    times.append(now)

    mentioned = bot.user.mentioned_in(message)
    replied_to_bot = (
        message.reference is not None and
        isinstance(message.reference.resolved, discord.Message) and
        message.reference.resolved.author == bot.user
    )

    if mentioned or replied_to_bot:
        await handle_reply_or_mention(message, user_id)

    await bot.process_commands(message)


@bot.command(name="store")
async def store_cmd(ctx, state: str):
    global STORE_MESSAGES
    state = state.lower()
    if state == "on":
        STORE_MESSAGES = True
        await ctx.send("ذخیره فعال شد")
    elif state == "off":
        STORE_MESSAGES = False
        await ctx.send("ذخیره خاموش شد")
    else:
        await ctx.send("استفاده: !store [on|off]")


@bot.command()
async def hello(ctx):
    await ctx.send("سلام! من اوستینا هستم 😋🌸")


async def run_bot():
    while True:
        try:
            await bot.start(TOKEN)
        except (ConnectionTimeoutError, ClientConnectorError, OSError) as e:
            print(f"⚠️ Connection error: {e}. تلاش دوباره در 10 ثانیه...")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"❌ خطای غیرمنتظره: {e}")
            break


async def _health(request):
    return web.Response(text="Bot is running ✅")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", _health)
    port = int(os.environ.get("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Health server listening on :{port}")


async def main():
    init_db()
    web_task = asyncio.create_task(start_web_server())
    bot_task = asyncio.create_task(run_bot())
    await asyncio.gather(web_task, bot_task)


if __name__ == "__main__":
    asyncio.run(main())
