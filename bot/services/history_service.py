# bot_friend/services/history_service.py
def rows_to_openai_messages(rows: list[tuple[int, str]], latest_user_text: str | None = None, max_chars: int = 3500) -> list[dict]:
    """
    rows: [(is_bot_reply, content)], تازه‌ترین در ابتدای لیست.
    خروجی: messages به ترتیب مکالمه (قدیمی → جدید)، با بودجه‌ی کاراکتر.
    """
    # به ترتیب قدیمی → جدید
    pairs = list(reversed(rows))
    out: list[dict] = []
    total = 0

    for is_bot, content in pairs:
        content = (content or "").strip()
        if not content:
            continue
        role = "assistant" if is_bot else "user"
        if total + len(content) > max_chars:
            # از ابتدای out جا باز کن (تاریخچه را تلخیص می‌کنیم)
            while out and total + len(content) > max_chars:
                removed = out.pop(0)
                total -= len(removed["content"])
        out.append({"role": role, "content": content})
        total += len(content)

    # اطمینان: پیام فعلی کاربر هم در انتها باشد
    if latest_user_text:
        t = latest_user_text.strip()
        if t and (not out or out[-1].get("content") != t):
            if total + len(t) > max_chars and out:
                while out and total + len(t) > max_chars:
                    removed = out.pop(0)
                    total -= len(removed["content"])
            out.append({"role": "user", "content": t})
    return out
