# bot_friend/services/openai_service.py
from openai import OpenAI

def build_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)
