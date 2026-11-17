import os
from dataclasses import dataclass, field

from dotenv import dotenv_values

from . import storage

ENV_FILE = storage.ROOT / ".env"


@dataclass(frozen=True)
class AIConfig:
    key: str = field(repr=False)
    base_url: str
    model: str
    embedding_model: str


def read_ai_config():
    local = dotenv_values(ENV_FILE, encoding="utf-8-sig")

    def value(name, default=""):
        return (os.getenv(name) or local.get(name) or default).strip()

    return AIConfig(
        key=value("AI_API_KEY"),
        base_url=value(
            "AI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/"),
        model=value("AI_MODEL", "qwen-plus"),
        embedding_model=value("EMBEDDING_MODEL", "text-embedding-v2"),
    )
