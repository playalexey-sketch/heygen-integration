"""Конфигурация агента.

Параметры читаются из переменных окружения, а при их отсутствии —
из .env-файлов (в порядке приоритета):
  1. переменные окружения (максимальный приоритет)
  2. <корень репозитория>/.env
  3. timeweb_agent/.env
  4. ~/.config/timeweb-agent/.env

Основные переменные:
  TIMEWEB_CLOUD_TOKEN  — JWT-токен панели Timeweb Cloud
                         (раздел «API и Terraform»: https://timeweb.cloud/my/api-keys)
  TIMEWEB_API_URL      — базовый URL API (по умолчанию https://api.timeweb.cloud/api/v1)

  TW_SSH_HOST          — IP/host сервера для SSH-деплоя
  TW_SSH_PORT          — порт SSH (по умолчанию 22)
  TW_SSH_USER          — пользователь SSH (по умолчанию root)
  TW_SSH_PASSWORD      — пароль SSH
  TW_SSH_KEY_PATH      — путь к приватному SSH-ключу
  TW_SSH_KEY_PASSPHRASE — парольная фраза ключа (опционально)

  TW_YES               — 1: автоматически подтверждать опасные действия
  TW_JSON              — 1: вывод всех команд в формате JSON
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_ENV_FILES = [
    REPO_ROOT / ".env",
    Path(__file__).resolve().parent / ".env",
    Path.home() / ".config" / "timeweb-agent" / ".env",
]


def _load_env_files() -> None:
    for path in _ENV_FILES:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # переменные окружения имеют приоритет
                os.environ.setdefault(key, value)
        except OSError:
            continue


_load_env_files()


def get(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    value = get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


API_TOKEN = get("TIMEWEB_CLOUD_TOKEN") or get("TIMEWEB_API_TOKEN")
API_BASE_URL = get("TIMEWEB_API_URL", "https://api.timeweb.cloud/api/v1").rstrip("/")
API_TIMEOUT = int(get("TIMEWEB_API_TIMEOUT", "60") or 60)
API_RETRIES = int(get("TIMEWEB_API_RETRIES", "5") or 5)

SSH_HOST = get("TW_SSH_HOST")
SSH_PORT = int(get("TW_SSH_PORT", "22") or 22)
SSH_USER = get("TW_SSH_USER", "root")
SSH_PASSWORD = get("TW_SSH_PASSWORD")
SSH_KEY_PATH = get("TW_SSH_KEY_PATH")
SSH_KEY_PASSPHRASE = get("TW_SSH_KEY_PASSPHRASE")

AUTO_YES = get_bool("TW_YES")
JSON_OUTPUT = get_bool("TW_JSON")

TOKEN_HELP = (
    "Не найден токен Timeweb Cloud.\n"
    "1. Откройте https://timeweb.cloud/my/api-keys (раздел «API и Terraform»).\n"
    "2. Создайте токен с правами на управление ресурсами.\n"
    "3. Сохраните его в файл .env в корне репозитория:\n"
    "       TIMEWEB_CLOUD_TOKEN=<ваш_токен>\n"
    "   или экспортируйте переменную окружения TIMEWEB_CLOUD_TOKEN.\n"
    "Файл .env добавлен в .gitignore и не попадёт в Git."
)


def require_token() -> str:
    if not API_TOKEN:
        raise SystemExit(TOKEN_HELP)
    return API_TOKEN


def mask(secret: str | None) -> str:
    """Маскирует секрет для безопасного вывода в лог."""
    if not secret:
        return "<пусто>"
    if len(secret) <= 8:
        return "***"
    return secret[:4] + "…" + secret[-4:]
