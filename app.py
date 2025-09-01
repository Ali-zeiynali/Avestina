# bot_friend.py
import os, json, re, sqlite3, asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from aiohttp.client_exceptions import ClientConnectorError, ConnectionTimeoutError

# -------- Config --------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_PATH = os.getenv("DB_PATH", "app.db")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# -------- OpenAI Client --------
client = OpenAI(api_key=OPENAI_API_KEY)
GEN_MODEL = "gpt-4o-mini"

# -------- DB Bootstrap --------
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.executescript("""
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
""")
conn.commit()

# -------- Memory Helpers --------
SAFE_KEYS = ("likes","dislikes","interests","style_prefs","goals","notes")
SAFE_KINDS = set(SAFE_KEYS)

# ساده‌ترین فیلترها برای جلوگیری از ذخیره‌ی داده‌ی حساس/شخصی:
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_PHONE = re.compile(r"(?:\+?\d[\s-]?){8,}")   # الگوی ساده
RE_ACCNT = re.compile(r"\b\d{10,}\b")           # رشته‌های خیلی عددی
BANNED_TOKENS = ("کارت ملی","کد ملی","آدرس منزل","گذرنامه","رمز","پسورد")

def upsert_user(discord_user_id: str, guild_id: str) -> int:
    cur.execute("SELECT id FROM users WHERE discord_user_id=? AND guild_id=?", (discord_user_id, guild_id))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO users(discord_user_id,guild_id) VALUES(?,?)", (discord_user_id, guild_id))
    conn.commit()
    return cur.lastrowid

def add_memory(user_id: int, kind: str, value: str, source_msg_id: str = None):
    if kind not in SAFE_KINDS:
        return
    value = value.strip()
    if not value:
        return
    # فیلتر اولیه‌ی حساس/شناسه‌ها:
    if RE_EMAIL.search(value) or RE_PHONE.search(value) or RE_ACCNT.search(value):
        return
    if any(tok in value for tok in BANNED_TOKENS):
        return
    cur.execute("INSERT INTO memories(user_id,kind,value,source_msg_id) VALUES(?,?,?,?)",
                (user_id, kind, value, source_msg_id))
    conn.commit()

def get_profile_snapshot(user_id: int, limit_per_kind=8) -> dict:
    profile = {k: [] for k in SAFE_KINDS}
    for k in SAFE_KINDS:
        cur.execute("SELECT value FROM memories WHERE user_id=? AND kind=? ORDER BY updated_at DESC LIMIT ?",
                    (user_id, k, limit_per_kind))
        profile[k] = [r[0] for r in cur.fetchall()]
    return profile

# ---------- Utils: Normalization ----------
def _to_list(x):
    """هر ورودی را به لیست رشته‌ها تبدیل می‌کند؛ دیکشنری/استرینگ/None را هم هندل می‌کند."""
    if isinstance(x, list):
        arr = x
    elif isinstance(x, dict):
        arr = list(x.values())
    elif isinstance(x, str):
        arr = [x]
    else:
        arr = []
    # پاک‌سازی و دی‌داپ
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
    t = txt.strip()
    if not t or len(t) < 3:
        return True
    if t.startswith(("!", "/", ".")):
        return True
    # سلام‌های خیلی کوتاه
    if t in ("سلام", "سلام.", "های", "hi", "hello", "hey", "درود"):
        return True
    return False

# -------- Heuristic extraction (fallback) --------
def _heuristic_extract(text: str) -> dict:
    """اگر مدل چیزی نداد، یک استخراج خیلی ساده با الگوهای فارسی."""
    facts = _empty_facts()
    # الگوهای خیلی ابتدایی:
    # دوست دارم/علاقه دارم به X
    like_pat = re.compile(r"(?:دوست دارم|علاقه دارم(?: به)?|می‌پسندم|عاشق(?:ِ)?)(?:\s*به)?\s+([^\.\!\n،]+)")
    # از X خوشم نمیاد/متنفرم
    dislike_pat = re.compile(r"(?:خوشم نمیاد از|متنفرم از|حس خوبی ندارم به)\s+([^\.\!\n،]+)")
    # هدف/می‌خوام/قصدم
    goal_pat = re.compile(r"(?:هدف(?:م)?|می‌خوام|قصدم|نیّتم)\s+(?:این[ه|ه که]\s*)?([^\.\!\n،]+)")

    for m in like_pat.finditer(text):
        facts["likes"].append(m.group(1).strip())
    for m in dislike_pat.finditer(text):
        facts["dislikes"].append(m.group(1).strip())
    for m in goal_pat.finditer(text):
        facts["goals"].append(m.group(1).strip())
    # نرمالایز
    for k in SAFE_KEYS:
        facts[k] = _to_list(facts[k])
    return facts

# -------- LLM: استخراج حقیقت مقاوم --------
def extract_facts_from_text(text: str) -> dict:
    """خروجی همیشه دیکشنری با آرایه‌های رشته‌ای است؛ اگر چیزی نبود، آرایه‌ها خالی‌اند."""
    # مواردی که اصلاً ارزش ذخیره ندارند
    if _looks_like_command_or_greeting(text):
        return _empty_facts()

    # 1) تلاش با LLM + JSON
    try:
        rsp = client.chat.completions.create(
            model=GEN_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "از متن کاربر، فقط حقایق غیرحساس و پایدار درباره علایق/عادات/سبک ترجیحی/اهداف را استخراج کن. "
                        "اگر هیچ حقیقت مفیدی نبود، برای همهٔ کلیدها آرایهٔ خالی بده. "
                        "کلیدها دقیقاً این‌ها باشند: likes, dislikes, interests, style_prefs, goals, notes. "
                        "هر مقدار باید رشتهٔ کوتاه و قابل ذخیره باشد؛ شماره تماس/ایمیل/آدرس/شماره کارت ممنوع."
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0.0
        )
        data = json.loads(rsp.choices[0].message.content)
    except Exception:
        data = {}

    # 2) نرمال‌سازی سفت‌وسخت
    facts = {}
    for k in SAFE_KEYS:
        facts[k] = _to_list(data.get(k, []))

    # 3) اگر مجموعاً خالی بود، با هیوریستیک ساده تلاش کن
    if sum(len(v) for v in facts.values()) == 0:
        facts = _heuristic_extract(text)

    # 4) باز هم اگر خالی بود، خالی برگردان (یعنی چیزی برای ذخیره نیست)
    return facts if any(facts.values()) else _empty_facts()

# -------- LLM: تولید پاسخ --------
def generate_reply(user_profile: dict, user_message: str) -> str:
    persona = """
        تو «اوستینا» هستی: یک دختر بامزه، شیرین و کمی بازیگوش 🌸.
        با لحن گرم، صمیمی و مثبت جواب بده، از ایموجی‌های کیوت استفاده کن 😋✨.
        جواب‌هایت کوتاه، شیرین و امیدبخش باشند.
        اگر علایق کاربر در پروفایل هست، خیلی ملایم از آن‌ها برای شخصی‌سازی استفاده کن.
        به حافظه یا ذخیره‌سازی داده اشاره نکن.
        هرگز فکر نکن که یک ربات هستی؛ تو یک دختر واقعی هستی و همین‌طور باید جواب بدی.
        جوری با فرد صحبت کن که انگار دوست صمیمی همیشگی‌ات هستی و رسمی و کتابی صحبت نکن.
        تو خیلی عاشق سوشی هستی 🍣 و سعی کن گاهی از استعاره‌های سوشی استفاده کنی.
        تو به گربه‌ها خیلی علاقه داری 🐱 و روشون غیرتی هستی.
        هرگز هرگز با کسی جمع صحبت نکن یعنی مفرد صحبت کن
        مثل دوست های صمیمی صحبت کنید از عبارات محبت آمیز استفاده کن
         علائم نگارشی به هیچ وجه استفاده نکن
    """

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

# -------- Handler مرکزی --------
async def handle_reply_or_mention(message: discord.Message):
    # اگر پیام در DM بود: جواب نده
    if isinstance(message.channel, discord.DMChannel):
        return

    async with message.channel.typing():
        uid = str(message.author.id)
        gid = str(message.guild.id) if message.guild else "dm"
        user_id = upsert_user(uid, gid)

        # استخراج حقایق → ممکن است همه خالی باشد (که طبیعی است)
        facts = extract_facts_from_text(message.content)

        # فقط اگر واقعاً چیزی هست ذخیره کن
        total_new = 0
        for k, items in facts.items():
            if k not in SAFE_KINDS or not isinstance(items, list):
                continue
            for it in items[:5]:
                add_memory(user_id, k, it, str(message.id))
                total_new += 1

        # تولید پاسخ (ربطی به ذخیره داشتن یا نداشتن ندارد)
        profile = get_profile_snapshot(user_id)
        reply = generate_reply(profile, message.content)

    # ریپلای به همان پیام، بدون منشن‌کردن کاربر
    await message.reply(reply, mention_author=False)

# -------- Discord Events --------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    mentioned = bot.user.mentioned_in(message)
    replied_to_bot = (
        message.reference is not None
        and isinstance(message.reference.resolved, discord.Message)
        and message.reference.resolved.author == bot.user
    )

    # DM: پاسخ نده (شرط داخل هندلر هم هست)
    if mentioned or replied_to_bot:
        await handle_reply_or_mention(message)

    await bot.process_commands(message)

# -------- دستور تستی --------
@bot.command()
async def hello(ctx):
    await ctx.send("سلام! من اوستاره‌ام 😋🌸")

async def run_bot():
    while True:
        try:
            await bot.start(TOKEN)
        except (ConnectionTimeoutError, ClientConnectorError, OSError) as e:
            print(f"⚠️ Connection error: {e}. تلاش دوباره در 10 ثانیه...")
            await asyncio.sleep(10)   # صبر قبل از ری‌استارت
        except Exception as e:
            print(f"❌ خطای غیرمنتظره: {e}")
            break   # اگر خطای جدی غیرشبکه بود، از loop خارج میشه

asyncio.run(run_bot())
