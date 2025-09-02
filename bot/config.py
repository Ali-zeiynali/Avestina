# bot_friend/config.py
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    token: str
    openai_api_key: str
    db_path: str
    model: str
    msg_window_seconds: int
    msg_limit: int
    web_port: int

def get_settings() -> Settings:
    db_path = os.getenv("DB_PATH", "database/app.db")
    if not os.path.isabs(db_path):
        root = Path(__file__).resolve().parent.parent
        db_path = str((root / db_path).resolve())

    return Settings(
        token=os.getenv("DISCORD_TOKEN", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        db_path=db_path,
        model=os.getenv("GEN_MODEL", "gpt-4.1-mini"),
        msg_window_seconds=int(os.getenv("MESSAGE_WINDOW", "60")),
        msg_limit=int(os.getenv("MESSAGE_LIMIT", "10")),
        web_port=int(os.getenv("PORT", "10000")),
    )
