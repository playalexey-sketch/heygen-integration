"""Конфигурация бота: читает переменные окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv опционален, если переменные заданы в окружении
    pass


def parse_ids(raw: str) -> set[int]:
    """Разбирает список Telegram ID: '123, 456; 789' -> {123, 456, 789}."""
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return ids


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset = field(default_factory=frozenset)
    data_dir: Path = Path("bot_data")
    web_port: int = 8080
    web_password: str = ""
    telegram_proxy: str = ""

    @property
    def stages_path(self) -> Path:
        return self.data_dir / "stages.json"

    @property
    def password_path(self) -> Path:
        return self.data_dir / "admin_password.txt"

    @property
    def proxy_path(self) -> Path:
        return self.data_dir / "proxy.txt"

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or "PASTE" in token.upper():
            raise SystemExit(
                "BOT_TOKEN не задан.\n"
                "1) Скопируйте .env.example в .env\n"
                "2) Получите токен у @BotFather и впишите его в BOT_TOKEN.\n"
                "   (При запуске через Docker токен берётся из .env — проверьте файл.)"
            )
        return cls(
            bot_token=token,
            admin_ids=frozenset(parse_ids(os.getenv("ADMIN_ID", ""))),
            data_dir=Path(os.getenv("DATA_DIR", "bot_data")).expanduser(),
            web_port=int(os.getenv("WEB_PORT", "8080") or 8080),
            web_password=os.getenv("ADMIN_PASSWORD", "").strip(),
            telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip(),
        )
