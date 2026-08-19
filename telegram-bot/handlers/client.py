"""Клиентская панель: после /start бот проигрывает настроенную последовательность
этапов (сообщение → ссылка → ник ...) с задержками, заданными админом."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import CallbackQuery, Message

from sender import StageSequencer
from services import AdminService

from .admin import IsAdmin

router = Router(name="client")

HINT = "Просто нажмите /start — я пришлю всё по порядку 👌"


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    sequencer: StageSequencer,
    admin: AdminService,
):
    if not message.from_user:
        return
    if message.chat.type != "private":
        await message.answer("Я работаю в личке. Откройте чат со мной и нажмите /start.")
        return

    if admin.is_admin(message.from_user.id):
        await message.answer("⚙️ Вы администратор бота. Для управления этапами: /admin")
        return

    restarted = sequencer.start(message.bot, message.chat.id)
    if restarted:
        await message.answer("🔁 Перезапускаю последовательность заново…")
    else:
        await message.answer("👌 Готово! Сообщения придут по очереди, с установленными задержками.")


@router.callback_query(F.data == "client:restart")
async def cb_restart(
    cb: CallbackQuery,
    sequencer: StageSequencer,
    admin: AdminService,
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


@router.message(Command("help"), StateFilter(None))
async def cmd_help(message: Message, admin: AdminService):
    if not message.from_user or admin.is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("Я работаю в личке.")
        return
    await message.answer("Нажмите /start — я отправлю вам всё, что нужно, по очереди.")


@router.message(~IsAdmin(), F.text & F.text.startswith("/"), StateFilter(None))
async def unknown_command(message: Message, admin: AdminService):
    if not message.from_user or admin.is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        return
    await message.answer("Такой команды нет. Нажмите /start 🙂")


@router.message(~IsAdmin(), F.text & ~F.text.startswith("/"), StateFilter(None))
async def client_text(message: Message, admin: AdminService):
    if not message.from_user or admin.is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        return
    await message.answer(HINT)
