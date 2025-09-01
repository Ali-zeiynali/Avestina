# bot_friend.py
import os, json, re, sqlite3, asyncio, time
from collections import defaultdict, deque
import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectorError, ConnectionTimeoutError

# -------- Config --------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_PATH = os.getenv("DB_PATH", "instance/app.db")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# -------- Spam control --------
MESSAGE_WINDOW = 60  # seconds
MESSAGE_LIMIT = 10
_user_msg_times: dict[int, deque] = defaultdict(deque)

# -------- OpenAI Client --------
client = OpenAI(api_key=OPENAI_API_KEY)
GEN_MODEL = "gpt-4o-mini"

# -------- DB Helpers --------
def get_conn():
    # کانکشن جدا برای هر عملیات؛ از تداخل جلوگیری می‌کند
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
        -- جلوگیری از ذخیره‌ی تکراری یک حقیقت برای یک کاربر/نوع
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mem_user_kind_value
          ON memories(user_id, kind, value);
        -- ایندکس‌های مفید برای خواندن پروفایل
        CREATE INDEX IF NOT EXISTS ix_mem_user_kind_time
          ON memories(user_id, kind, updated_at DESC, created_at DESC);
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
    # فیلترهای ساده برای داده‌ی حساس
    if RE_EMAIL.search(value) or RE_PHONE.search(value) or RE_ACCNT.search(value):
        return
    if any(tok in value for tok in BANNED_TOKENS):
        return
    with get_conn() as conn:
        cur = conn.cursor()
        # UPSERT: اگر قبلاً همین حقیقت ذخیره شده بود، خطا نده
        cur.execute("""
            INSERT INTO memories(user_id,kind,value,source_msg_id)
            VALUES (?,?,?,?)
            ON CONFLICT(user_id, kind, value) DO UPDATE SET
              updated_at = CURRENT_TIMESTAMP
        """, (user_id, kind, value, source_msg_id))
        conn.commit()

def get_profile_snapshot(user_id: int, limit_per_kind=8) -> dict:
    profile = {k: [] for k in SAFE_KINDS}
    with get_conn() as conn:
        cur = conn.cursor()
        for k in SAFE_KINDS:
            cur.execute(
                "SELECT value FROM memories WHERE user_id=? AND kind=? "
                "ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                (user_id, k, limit_per_kind),
            )
            profile[k] = [r[0] for r in cur.fetchall()]
    return profile

# -------- Memory policy --------
SAFE_KEYS = ("likes","dislikes","interests","style_prefs","goals","notes")
SAFE_KINDS = set(SAFE_KEYS)

# جلوگیری از ذخیره‌ی داده‌ی شخصی/حساس
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_PHONE = re.compile(r"(?:\+?\d[\s-]?){8,}")
RE_ACCNT = re.compile(r"\b\d{10,}\b")
BANNED_TOKENS = ("کارت ملی","کد ملی","آدرس منزل","گذرنامه","رمز","پسورد")

# ---------- Normalization ----------
def _to_list(x):
    if isinstance(x, list):
        arr = x
    elif isinstance(x, dict):
        arr = list(x.values())
    elif isinstance(x, str):
        arr = [x]
    else:
        arr = []
    out, seen = [], set()
    for it in arr:
        if not isinstance(it, str):
            continue
        s = it.strip()
        if 2 <= len(s) <= 120:
            k = s.casefold()
            if k not in seen:
                seen.add(k)
                out.append(s)
    return out[:10]

def _empty_facts():
    return {k: [] for k in SAFE_KEYS}

def _looks_like_command_or_greeting(txt: str) -> bool:
    t = (txt or "").strip()
    if not t or len(t) < 3:
        return True
    if t.startswith(("!", "/", ".")):
        return True
    if t in ("سلام","سلام.","های","hi","hello","hey","درود"):
        return True
    return False

# -------- Heuristic fallback --------
def _heuristic_extract(text: str) -> dict:
    facts = _empty_facts()
    like_pat    = re.compile(r"(?:دوست دارم|علاقه دارم(?: به)?|می‌پسندم|عاشق(?:ِ)?)(?:\s*به)?\s+([^\.\!\n،]+)")
    dislike_pat = re.compile(r"(?:خوشم نمیاد از|متنفرم از|حس خوبی ندارم به)\s+([^\.\!\n،]+)")
    goal_pat    = re.compile(r"(?:هدف(?:م)?|می‌خوام|قصدم|نیّتم)\s+(?:این[ه|ه که]\s*)?([^\.\!\n،]+)")

    for m in like_pat.finditer(text):    facts["likes"].append(m.group(1).strip())
    for m in dislike_pat.finditer(text): facts["dislikes"].append(m.group(1).strip())
    for m in goal_pat.finditer(text):    facts["goals"].append(m.group(1).strip())

    for k in SAFE_KEYS:
        facts[k] = _to_list(facts[k])
    return facts

# -------- LLM: robust fact extraction --------
def extract_facts_from_text(text: str) -> dict:
    if _looks_like_command_or_greeting(text):
        return _empty_facts()
    try:
        rsp = client.chat.completions.create(
            model=GEN_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role":"system","content":
                 "از متن کاربر فقط حقایق غیرحساس و پایدار (likes, dislikes, interests, style_prefs, goals, notes) را "
                 "به صورت JSON برگردان. اگر چیزی نبود آرایه‌های خالی بده. اعداد حساس/ایمیل/تلفن/آدرس ممنوع."},
                {"role":"user","content": text}
            ],
            temperature=0.0
        )
        data = json.loads(rsp.choices[0].message.content)
    except Exception:
        data = {}

    facts = {k: _to_list(data.get(k, [])) for k in SAFE_KEYS}
    if sum(len(v) for v in facts.values()) == 0:
        facts = _heuristic_extract(text)
    return facts if any(facts.values()) else _empty_facts()

# -------- LLM: reply generation (شخصیت امن) --------
def generate_reply(user_profile: dict, user_message: str) -> str:
    # شخصیت امن و محترمانه
    persona = (
        "تو «اوستینا» هستی؛ یک دوست بامزه، شیرین و کمی بازیگوش 🌸. "
        "با لحن گرم و صمیمی جواب بده، از ایموجی‌های لطیف استفاده کن 😋✨. "
        "جواب‌ها کوتاه و امیدبخش. اگر کاربر بدحرفی کرد، محترمانه و محکم پاسخ بده ولی بی‌ادب نشو. "
        "اگر علایق کاربر در پروفایل هست، خیلی ملایم از آن‌ها برای شخصی‌سازی استفاده کن. "
        "به حافظه یا ذخیره‌سازی اشاره نکن."
    )
    mem = json.dumps(user_profile, ensure_ascii=False)
    rsp = client.chat.completions.create(
        model=GEN_MODEL,
        messages=[
            {"role": "system", "content": persona},
            {"role": "assistant", "content": f"(پروفایل کاربر برای زمینه): {mem}"},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7
    )
    return rsp.choices[0].message.content

# -------- Handler --------
async def handle_reply_or_mention(message: discord.Message):
    if isinstance(message.channel, discord.DMChannel):
        return

    async with message.channel.typing():
        uid = str(message.author.id)
        gid = str(message.guild.id) if message.guild else "dm"
        user_id = upsert_user(uid, gid)

        MAX_LEN = 800
        if len(message.content) <= MAX_LEN:
            facts = extract_facts_from_text(message.content)
            for k, items in facts.items():
                if k not in SAFE_KINDS or not isinstance(items, list):
                    continue
                for it in items[:5]:
                    # ذخیره غیرمسدودکننده
                    asyncio.create_task(
                        asyncio.to_thread(add_memory, user_id, k, it, str(message.id))
                    )

        profile = get_profile_snapshot(user_id)
        reply = generate_reply(profile, message.content)

    await message.reply(reply, mention_author=False)

# -------- Discord Events --------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # ساده‌ترین rate limit محلی
    uid = message.author.id
    now = time.time()
    times = _user_msg_times[uid]
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
        await handle_reply_or_mention(message)

    await bot.process_commands(message)

# -------- Test command --------
@bot.command()
async def hello(ctx):
    await ctx.send("سلام! من اوستینا هستم 😋🌸")

# -------- Auto-restart loop --------
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

# -------- Minimal web server for Render --------
async def _health(request):
    return web.Response(text="Bot is running ✅")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", _health)
    port = int(os.environ.get("PORT", "10000"))  # Render PORT
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Health server listening on :{port}")

# ---- start both (web + bot) ----
async def main():
    init_db()
    web_task = asyncio.create_task(start_web_server())
    bot_task = asyncio.create_task(run_bot())
    await asyncio.gather(web_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
