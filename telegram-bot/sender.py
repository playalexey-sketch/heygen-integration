"""Отправка этапов клиенту: логика отправки одного этапа и фоновый «секуэнсер».

Секуэнсер запускается при /start клиента и в фоне проигрывает этапы:
ждёт delay_seconds после предыдущего сообщения — и отправляет следующий.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from storage import CONTENT_LINK, CONTENT_NICKNAME, Stage, StageStorage

log = logging.getLogger("sender")

# Если ссылка на файл заканчивается одним из этих расширений — пробуем
# отправить его Telegram-ботом как вложение (send_document по URL).
FILE_EXTENSIONS = (
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".exe", ".dmg", ".iso", ".apk",
    ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi", ".mkv",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".json", ".xml", ".sql", ".db",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
)

RESTART_BUTTON_TEXT = "📥 Получить снова"


def is_direct_file_url(url: str) -> bool:
    """Да — если http(s)-ссылка ведёт прямо на файл (сужение по расширению)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return parts.path.lower().endswith(FILE_EXTENSIONS)


def _nickname_line(content: str) -> str | None:
    username = content.strip().lstrip("@").strip()
    if not username:
        return None
    return (
        "Связаться со мной в Telegram:\n"
        f"<a href=\"https://t.me/{username}\">{username}</a>"
    )


async def send_stage(bot: Bot, chat_id: int, stage: Stage, prefix: str | None = None) -> None:
    """Отправляет один этап. prefix — служебная подпись (используется в тестах)."""
    if stage.content_type == CONTENT_NICKNAME:
        line = _nickname_line(stage.content)
        if line:
            text = f"{prefix}\n\n{line}" if prefix else line
            await bot.send_message(chat_id, text, parse_mode="HTML")
            return
        log.warning("Этап %s: некорректный ник «%s», отправляю как обычный текст", stage.id, stage.content)

    body = stage.content.strip()

    if stage.content_type == CONTENT_LINK and is_direct_file_url(body):
        try:
            if prefix:
                await bot.send_document(chat_id, body, caption=prefix)
            else:
                await bot.send_document(chat_id, body)
            return
        except Exception as e:  # диск не отдал файл — присылаем саму ссылку
            log.warning("Не удалось отправить файл по ссылке %s (%s), отправляю ссылкой", body, e)

    text = f"{prefix}\n\n{body}" if prefix else body
    await bot.send_message(chat_id, text)


def restart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=RESTART_BUTTON_TEXT, callback_data="client:restart")]
        ]
    )


class StageSequencer:
    """Фоновые задачи проигрывания этапов: одна активная задача на чат."""

    def __init__(self, storage: StageStorage):
        self._storage = storage
        self._tasks: dict[int, asyncio.Task] = {}

    def start(self, bot: Bot, chat_id: int) -> bool:
        """Запускает (или перезапускает) последовательность. True — если перезапуск."""
        old = self._tasks.get(chat_id)
        restarted = bool(old and not old.done())
        if old and not old.done():
            old.cancel()
        self._tasks[chat_id] = asyncio.create_task(
            self._run(bot, chat_id), name=f"stages-{chat_id}"
        )
        return restarted

    def cancel(self, chat_id: int) -> None:
        task = self._tasks.get(chat_id)
        if task and not task.done():
            task.cancel()

    def active(self, chat_id: int) -> bool:
        task = self._tasks.get(chat_id)
        return bool(task and not task.done())

    async def _run(self, bot: Bot, chat_id: int) -> None:
        task = asyncio.current_task()
        try:
            stages = self._storage.ordered()
            if not stages:
                await bot.send_message(
                    chat_id,
                    "⚙️ Бот ещё не настроен. Попробуйте /start чуть позже.",
                )
                return
            for stage in stages:
                if stage.delay_seconds > 0:
                    await asyncio.sleep(stage.delay_seconds)
                await send_stage(bot, chat_id, stage)
            await bot.send_message(
                chat_id,
                "Если что-то потерялось — просто нажмите кнопку:",
                reply_markup=restart_kb(),
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Последовательность этапов для чата %s прервана", chat_id)
        finally:
            if self._tasks.get(chat_id) is task:
                self._tasks.pop(chat_id, None)


async def run_test(bot: Bot, chat_id: int, storage: StageStorage, live: bool) -> None:
    """Админ-прогон сценария: live=True — с реальными задержками, False — сразу."""
    stages = storage.ordered()
    if not stages:
        await bot.send_message(chat_id, "🧪 Нет включённых этапов — добавьте их в /admin.")
        return
    total = len(stages)
    for i, stage in enumerate(stages, 1):
        wait = stage.delay_seconds if live else 0
        if wait > 0:
            await asyncio.sleep(wait)
        await send_stage(bot, chat_id, stage, prefix=f"🧪 Тест, этап {i}/{total}")
    await bot.send_message(chat_id, "✅ Тест завершён.")
