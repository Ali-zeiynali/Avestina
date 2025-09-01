import re

SAFE_KEYS = ("likes","dislikes","interests","style_prefs","goals","notes")
SAFE_KINDS = set(SAFE_KEYS)

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_PHONE = re.compile(r"(?:\+?\d[\s-]?){8,}")
RE_ACCNT = re.compile(r"\b\d{10,}\b")
BANNED_TOKENS = ("کارت ملی","کد ملی","آدرس منزل","گذرنامه","رمز","پسورد")
