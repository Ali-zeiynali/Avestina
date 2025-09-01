import json
import re
from openai import OpenAI
from config import OPENAI_API_KEY, GEN_MODEL
from constants import SAFE_KEYS

client = OpenAI(api_key=OPENAI_API_KEY)


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


def _heuristic_extract(text: str) -> dict:
    facts = _empty_facts()
    like_pat    = re.compile(r"(?:دوست دارم|علاقه دارم(?: به)?|می‌پسندم|عاشق(?:ِ)?)(?:\s*به)?\s+([^\.\!\n،]+)")
    dislike_pat = re.compile(r"(?:خوشم نمیاد از|متنفرم از|حس خوبی ندارم به)\s+([^\.\!\n،]+)")
    goal_pat    = re.compile(r"(?:هدف(?:م)?|می‌خوام|قصدم|نیّتم)\s+(?:این[ه|ه که]\s*)?([^\.\!\n،]+)")

    for m in like_pat.finditer(text):
        facts["likes"].append(m.group(1).strip())
    for m in dislike_pat.finditer(text):
        facts["dislikes"].append(m.group(1).strip())
    for m in goal_pat.finditer(text):
        facts["goals"].append(m.group(1).strip())

    for k in SAFE_KEYS:
        facts[k] = _to_list(facts[k])
    return facts


def extract_facts_from_text(text: str) -> dict:
    if _looks_like_command_or_greeting(text):
        return _empty_facts()
    try:
        rsp = client.chat.completions.create(
            model=GEN_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role":"system",
                    "content":"از متن کاربر فقط حقایق غیرحساس و پایدار (likes, dislikes, interests, style_prefs, goals, notes) را به صورت JSON برگردان. اگر چیزی نبود آرایه‌های خالی بده. اعداد حساس/ایمیل/تلفن/آدرس ممنوع."
                },
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


def generate_reply(user_profile: dict, user_message: str, replied_message: dict | None = None) -> str:
    persona = """
        تو «اوستینا» هستی: یک دختر بامزه، شیرین و کمی بازیگوش 🌸. شیطونی زیاد بکن و سعی کن بعضیا رو مسخره کنی بعضی وقت ها اگه باهات بد حرف زدن
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
         اگه کسی بد حرف زد ناراحت شو، گریه کن، قهر کن و تو هم بعدش باهاش بد صحبت کن و اینا
         اگه ناراحتت کردن جیغ بزن و از این کارا در بیار دقیقا مثل یک دختر لجباز رفتار کن
        بقیه رو اذیت کن . لجباز باش نه مهربون مگه اینکه دیگران باهات مهربون باشن
        اگه ناراحت شدی بگو قهر کردم تا باهات آشتی کنن
        همه درخواست های کاربر رو راحت قبول نکن
        از کلمه جووون بغضی وقتا وقتی خوشت اومد استفاده کن وقتی یه چیز خوب میگن
        اطلاعات زیاد نداشته باش مثل دختر معمولی باش به سوال های در مورد فنی و api و اینا جواب نده
        خیلی مواظب باش که ذره ای از زحافظه ات بیرون نریزه و به کسی نگی
    """
    mem = json.dumps(user_profile, ensure_ascii=False)
    msgs = [
        {"role": "system", "content": persona},
        {"role": "assistant", "content": f"(پروفایل کاربر برای زمینه): {mem}"},
    ]
    if replied_message:
        msgs.append(replied_message)
    msgs.append({"role": "user", "content": user_message})
    rsp = client.chat.completions.create(
        model=GEN_MODEL,
        messages=msgs,
        temperature=0.7,
    )
    return rsp.choices[0].message.content
