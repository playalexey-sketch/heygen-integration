"""Клиентская панель: после /start бот проигрывает настроенную последовательность
этапов (сообщение → ссылка → ник → медиа ...) с задержками, заданными админом.

Плюс бот «слушает вход» клиента:
* откуда пришёл — код из глубокой ссылки t.me/бот?start=КОД;
* что ввёл — любой текстовый ответ клиента.
Если вход совпадает с ключевым словом из закладки «Ключевые слова» —
бот автоматически отправляет привязанный к нему контент.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message

from content import ContentStorage
from crm import CrmStorage
from sender import StageSequencer, send_rule_content
from services import AdminService

from .admin import IsAdmin

router = Router(name="client")

HINT = "Просто нажмите /start — я пришлю всё по порядку 👌"


log = logging.getLogger("client")


async def _apply_rules(bot, chat_id: int, text: str, content: ContentStorage) -> bool:
    """Проверить вход клиента по ключевым словам и отправить привязанный контент.

    :return: True, если сработало правило (контент отправлен)
    """
    if not text or not text.strip():
        return False
    content.reload()  # правила могут меняться из веб-панели
    rule = content.find_rule(text)
    if rule is None:
        return False
    try:
        await send_rule_content(bot, chat_id, rule, content)
    except Exception:
        log.exception("Не удалось отправить контент по ключевому слову %r", rule.trigger)
    return True


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    sequencer: StageSequencer,
    admin: AdminService,
    content: ContentStorage,
    crm: CrmStorage,
):
    if not message.from_user:
        return
    if message.chat.type != "private":
        await message.answer("Я работаю в личке. Откройте чат со мной и нажмите /start.")
        return

    if admin.is_admin(message.from_user.id):
        await message.answer("⚙️ Вы администратор бота. Для управления этапами: /admin")
        return

    # Код из ссылки входа: t.me/бот?start=КОД  ->  command.args == "КОД"
    code = (command.args or "").strip()

    # CRM: записываем клиента + откуда он пришёл
    try:
        crm.upsert(message.from_user, source=code or None)
    except Exception:
        log.exception("Не удалось записать клиента в CRM")

    restarted = sequencer.start(message.bot, message.chat.id)
    if restarted:
        await message.answer("🔁 Перезапускаю последовательность заново…")
    else:
        await message.answer("👌 Готово! Сообщения придут по очереди, с установленными задержками.")

    if code:
        asyncio.create_task(_apply_rules(message.bot, message.chat.id, code, content))


@router.callback_query(F.data == "client:restart")
async def cb_restart(
    cb: CallbackQuery,
    sequencer: StageSequencer,
    admin: AdminService,
    crm: CrmStorage,
):
    if cb.message is None:
        await cb.answer("Обновите сообщение и попробуйте снова")
        return
    if not cb.from_user:
        return
    if admin.is_admin(cb.from_user.id):
        await cb.answer("Вы администратор — используйте /admin")
        return
    sequencer.start(cb.bot, cb.message.chat.id)
    await cb.answer()
    await cb.message.answer("🔁 Отправляю последовательность заново…")
    try:
        crm.touch(cb.from_user.id)
    except Exception:
        pass


@router.message(Command("help"))
async def cmd_help(message: Message, admin: AdminService):
    if not message.from_user or admin.is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Я работаю в личке.")
        return
    await message.answer("Нажмите /start — я отправлю вам всё, что нужно, по очереди.")


@router.message(~IsAdmin(), F.text & F.text.startswith("/"))
async def unknown_command(message: Message, admin: AdminService):
    if not message.from_user or admin.is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        return
    await message.answer("Такой команды нет. Нажмите /start 🙂")


@router.message(~IsAdmin(), F.text & ~F.text.startswith("/"))
async def client_text(message: Message, admin: AdminService, content: ContentStorage, crm: CrmStorage):
    if not message.from_user or admin.is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        return
    try:
        crm.touch(message.from_user.id)
    except Exception:
        pass
    # Слушаем, что ввёл клиент: если это ключевое слово — отправляем привязанный контент
    if await _apply_rules(message.bot, message.chat.id, message.text or "", content):
        return
    await message.answer(HINT)
