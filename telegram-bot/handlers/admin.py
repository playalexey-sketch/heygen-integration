"""Админ-панель: настройка этапов сценария.

Админ задаёт количество и содержание этапов: текст сообщения, задержка
после предыдущего сообщения, тип контента (текст / ссылка на файл / ник).
Клиент после /start получает этапы строго по порядку.
"""
from __future__ import annotations

import logging
import re

import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from content import KIND_AUDIO, KIND_DOCUMENT, KIND_PHOTO, KIND_VIDEO, ContentStorage, guess_kind
from sender import run_test
from services import AdminService
from storage import CONTENT_LINK, CONTENT_MEDIA, CONTENT_NICKNAME, CONTENT_TEXT, Stage, StageStorage

router = Router(name="admin")
log = logging.getLogger("admin")


class IsAdmin(BaseFilter):
    """Сообщение от администратора (по ADMIN_ID из .env или первому /admin)."""

    async def __call__(self, message: Message, admin: AdminService) -> bool:
        user = message.from_user
        return bool(user) and admin.is_admin(user.id)

MAX_DELAY = 24 * 3600

TYPE_ICONS = {
    CONTENT_TEXT: "📄",
    CONTENT_LINK: "🔗",
    CONTENT_NICKNAME: "👤",
    CONTENT_MEDIA: "🎬",
}

TYPE_PROMPTS = {
    CONTENT_TEXT: "Шаг 3/3 — Отправьте текст сообщения обычным сообщением (можно многострочным).",
    CONTENT_LINK: (
        "Шаг 3/3 — Отправьте ссылку на файл: Яндекс Диск, Google Drive, MEGA и т.п. "
        "Если ссылка ведёт прямо на файл (например, .pdf, .zip) — я отправлю его как вложение."
    ),
    CONTENT_NICKNAME: "Шаг 3/3 — Отправьте ник в Telegram: @username или username.",
    CONTENT_MEDIA: (
        "Шаг 3/3 — Отправьте файл сообщением: фото, видео, аудио или любой файл. "
        "Я сохраню его в боте, и он будет уходить клиентам."
    ),
}

HELP_TEXT = (
    "📖 Как устроена панель\n"
    "\n"
    "Бот после /start клиента отправляет ему этапы по порядку.\n"
    "Каждый этап = задержка (сек) + контент:\n"
    "📄 — текстовое сообщение (например, приветствие)\n"
    "🔗 — ссылка на файл с диска (Яндекс, Google, MEGA);\n"
    "   прямые ссылки на файлы (.pdf, .zip ...) уходят вложением\n"
    "👤 — ник в Telegram, превращается в кликабельную ссылку\n"
    "\n"
    "⏱ Задержка = сколько ждать ПОСЛЕ предыдущего сообщения бота.\n"
    "\n"
    "Команды:\n"
    "/admin — открыть панель\n"
    "/add — добавить этап (мастер)\n"
    "/stages — список этапов\n"
    "/edit <N> — отредактировать этап N\n"
    "/del <N> — удалить этап N\n"
    "/up <N>, /down <N> — поднять / опустить этап\n"
    "/on <N>, /off <N> — включить / выключить этап\n"
    "/test — прогнать сценарий сразу (без задержек)\n"
    "/test_live — прогнать сценарий с реальными задержками\n"
    "/cancel — отменить текущий мастер"
)


# ----------------------------- FSM-мастер -----------------------------

class Wizard(StatesGroup):
    delay = State()
    ctype = State()
    content = State()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список этапов", callback_data="menu:stages")],
            [
                InlineKeyboardButton(text="➕ Добавить этап", callback_data="wizard:add"),
                InlineKeyboardButton(text="🧪 Тест (без задержек)", callback_data="test:fast"),
            ],
            [
                InlineKeyboardButton(text="▶️ Тест (с задержками)", callback_data="test:live"),
                InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
            ],
        ]
    )


def type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Текстовое сообщение", callback_data="type:text")],
            [InlineKeyboardButton(text="🔗 Ссылка на файл", callback_data="type:link")],
            [InlineKeyboardButton(text="👤 Ник в Telegram", callback_data="type:nickname")],
            [InlineKeyboardButton(text="🎬 Медиа (фото/видео/аудио/файл)", callback_data="type:media")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="wizard:cancel")],
        ]
    )


def stages_kb(stages: list[Stage]) -> InlineKeyboardMarkup:
    rows = []
    for i, stage in enumerate(stages, 1):
        rows.append(
            [
                InlineKeyboardButton(text=f"✏️ {i}", callback_data=f"wizard:edit:{stage.id}"),
                InlineKeyboardButton(text="⬆️", callback_data=f"move:{stage.id}:-1"),
                InlineKeyboardButton(text="⬇️", callback_data=f"move:{stage.id}:1"),
                InlineKeyboardButton(text="🔁", callback_data=f"toggle:{stage.id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"del:{stage.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить этап", callback_data="wizard:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _snippet(text: str, limit: int = 64) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def render_stages(stages: StageStorage, content: "ContentStorage | None" = None) -> tuple[str, InlineKeyboardMarkup]:
    stages = stages.all()
    if not stages:
        return (
            "Список этапов пуст.\n"
            "Добавьте первый этап — бот отправит его клиенту сразу после /start.",
            stages_kb([]),
        )
    lines = ["📋 Этапы (сверху вниз, в порядке отправки):", ""]
    for i, s in enumerate(stages, 1):
        status = "✅" if s.enabled else "⏸"
        delay = "сразу после прошлого" if s.delay_seconds == 0 else f"через {s.delay_seconds} с"
        lines.append(f"{i}. {status} {TYPE_ICONS[s.content_type]} {delay}")
        if s.content_type == CONTENT_MEDIA:
            m = content.get_media(s.content) if content else None
            label = f"файл: {m.name}" if m else "файл не найден!"
        else:
            label = f"«{_snippet(s.content)}»"
        lines.append(f"    {label}")
    lines += ["", "Кнопки: ✏️ ред. | ⬆️⬇️ порядок | 🔁 вкл/выкл | 🗑 удалить"]
    return "\n".join(lines), stages_kb(stages)


async def answer_cb(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        if cb.message is not None and cb.message.text:
            await cb.message.edit_text(text, reply_markup=kb)
            return
    except Exception:
        pass
    if cb.message is not None:
        await cb.message.answer(text, reply_markup=kb)


async def start_wizard(
    message: Message,
    stage: Stage | None,
    position: int | None,
    state: FSMContext,
) -> None:
    title = f"✏️ Редактирование этапа {position}" if stage else "➕ Новый этап"
    current = f" (сейчас: {stage.delay_seconds} с)" if stage else ""
    await state.set_state(Wizard.delay.state)
    await state.update_data(mode="edit" if stage else "add", stage_id=stage.id if stage else None)
    await message.answer(
        f"{title}\n\n"
        f"Шаг 1/3 — Введите задержку в секундах после предыдущего сообщения бота"
        f" (0 = сразу){current}."
    )


async def guard_admin(message: Message, admin: AdminService) -> bool:
    uid = message.from_user.id if message.from_user else None
    if uid is None:
        return False
    if admin.is_admin(uid):
        return True
    if admin.allow_anyone() and message.chat.type == "private":
        admin.promote(uid)
        await message.answer(
            f"✅ Вы стали администратором бота (ID: {uid}).\n"
            "Рекомендую прописать свой ID в ADMIN_ID в .env — так панель "
            "будет доступна только вам."
        )
        return True
    await message.answer("⛔ Доступ запрещён.")
    return False


def _cb_admin_ok(cb: CallbackQuery, admin: AdminService) -> bool:
    uid = cb.from_user.id if cb.from_user else None
    return bool(uid) and admin.is_admin(uid)


async def _deny_cb(cb: CallbackQuery) -> None:
    await cb.answer("⛔ Доступ запрещён", show_alert=True)


def _stage_arg(message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return None


# ----------------------------- команды -----------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message, admin: AdminService):
    if not await guard_admin(message, admin):
        return
    await message.answer("⚙️ Админ-панель. Выберите действие:", reply_markup=main_menu_kb())


@router.message(Command("stages"))
async def cmd_stages(message: Message, state: FSMContext, admin: AdminService, stages: StageStorage, content: ContentStorage):
    if not await guard_admin(message, admin):
        return
    text, kb = render_stages(stages)
    await message.answer(text, reply_markup=kb)


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext, admin: AdminService):
    if not await guard_admin(message, admin):
        return
    await start_wizard(message, None, None, state)


@router.message(Command("edit"))
async def cmd_edit(
    message: Message,
    state: FSMContext,
    admin: AdminService,
    stages: StageStorage,
):
    if not await guard_admin(message, admin):
        return
    n = _stage_arg(message)
    stage = stages.get_by_position(n) if n else None
    if stage is None:
        await message.answer("Укажите номер этапа: /edit <N> (список — /stages)")
        return
    await start_wizard(message, stage, n, state)


@router.message(Command("del"))
async def cmd_del(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    n = _stage_arg(message)
    stage = stages.get_by_position(n) if n else None
    if stage is not None and stages.remove(stage.id):
        await message.answer(f"🗑 Этап {n} удалён.")
    else:
        await message.answer("Укажите существующий номер: /del <N> (список — /stages)")


@router.message(Command("up"))
async def cmd_up(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    n = _stage_arg(message)
    stage = stages.get_by_position(n) if n else None
    if stage and stages.move(stage.id, -1):
        await message.answer(f"⬆️ Этап {n} поднят на позицию {stages.index_of(stage) + 1}.")
    else:
        await message.answer("Этап уже наверху (или номер не найден).")


@router.message(Command("down"))
async def cmd_down(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    n = _stage_arg(message)
    stage = stages.get_by_position(n) if n else None
    if stage and stages.move(stage.id, 1):
        await message.answer(f"⬇️ Этап {n} опущен на позицию {stages.index_of(stage) + 1}.")
    else:
        await message.answer("Этап и так последняя позиция (или номер не найден).")


async def _set_enabled(message: Message, stages: StageStorage, n: int | None, value: bool) -> None:
    stage = stages.get_by_position(n) if n else None
    if stage is None:
        await message.answer(f"Укажите существующий номер: /{'on' if value else 'off'} <N> (список — /stages)")
        return
    stages.set_enabled(stage.id, value)
    if value:
        await message.answer(f"✅ Этап {n} включён.")
    else:
        await message.answer(f"⏸ Этап {n} выключен.")


@router.message(Command("on"))
async def cmd_on(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    await _set_enabled(message, stages, _stage_arg(message), True)


@router.message(Command("off"))
async def cmd_off(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    await _set_enabled(message, stages, _stage_arg(message), False)


@router.message(Command("test"))
async def cmd_test(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    await message.answer("🧪 Прогоняю сценарий без задержек…")
    await run_test(message.bot, message.chat.id, stages, live=False)


@router.message(Command("test_live"))
async def cmd_test_live(message: Message, admin: AdminService, stages: StageStorage):
    if not await guard_admin(message, admin):
        return
    await message.answer("▶️ Прогоняю сценарий с реальными задержками (может занять время)…")
    await run_test(message.bot, message.chat.id, stages, live=True)


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext, admin: AdminService):
    if not message.from_user or not admin.is_admin(message.from_user.id):
        return
    if await state.get_state():
        await state.clear()
        await message.answer("❌ Отменено.")
    else:
        await message.answer("Нечего отменять.")


# --------------------- шаг 1: задержка (текстом) ---------------------

@router.message(Wizard.delay, F.text)
async def wizard_delay(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно неотрицательное целое число — секунды. Или /cancel.")
        return
    delay = int(raw)
    if delay > MAX_DELAY:
        await message.answer(f"Слишком много: максимум {MAX_DELAY} секунд (сутки). Или /cancel.")
        return
    await state.update_data(delay=delay)
    await message.answer("Шаг 2/3 — Какой тип контента?", reply_markup=type_kb())
    await state.set_state(Wizard.ctype.state)


# --------------------- шаг 2: тип (кнопки) ---------------------

@router.callback_query(Wizard.ctype, F.data.startswith("type:"))
async def wizard_type(cb: CallbackQuery, state: FSMContext):
    ctype = cb.data.split(":", 1)[1]
    if ctype not in (CONTENT_TEXT, CONTENT_LINK, CONTENT_NICKNAME):
        await cb.answer("Неизвестный тип", show_alert=True)
        return
    await state.update_data(ctype=ctype)
    await state.set_state(Wizard.content.state)
    await cb.answer()
    if cb.message is not None:
        await cb.message.answer(TYPE_PROMPTS[ctype])


# --------------------- шаг 3: контент (текстом) ---------------------

@router.message(Wizard.content, F.text)
async def wizard_content(message: Message, state: FSMContext, stages: StageStorage, content: ContentStorage):
    data = await state.get_data()
    ctype = data.get("ctype", CONTENT_TEXT)
    raw = (message.text or "").strip()

    if ctype == CONTENT_MEDIA:
        await message.answer(
            "Для медиа-этапа нужно отправить сам файл (фото/видео/аудио/файл), а не текст. "
            "Отправьте файл сообщением, или /cancel."
        )
        return

    if ctype == CONTENT_LINK:
        if not re.fullmatch(r"https?://\S+", raw):
            await message.answer("Это не похоже на ссылку. Пришлите ссылку вида https://... (или /cancel).")
            return
        content = raw
    elif ctype == CONTENT_NICKNAME:
        username = raw.lstrip("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            await message.answer(
                "Ник выглядит как @username: 5–32 символа, латиница, цифры, подчёркивание. (или /cancel)"
            )
            return
        content = "@" + username
    else:
        if not raw:
            await message.answer("Текст не может быть пустым.")
            return
        content = raw

    if data.get("mode") == "edit" and stages.get(data.get("stage_id", -1)) is not None:
        stages.update(data["stage_id"], delay_seconds=data.get("delay", 0), content_type=ctype, content=content)
        await message.answer("✅ Этап обновлён. Текущий список:")
    else:
        stages.add(data.get("delay", 0), ctype, content)
        await message.answer(f"✅ Этап добавлен. Всего этапов: {len(stages.all())}. Список:")

    await state.clear()
    text, kb = render_stages(stages, content)
    await message.answer(text, reply_markup=kb)


@router.message(Wizard.content, F.photo | F.video | F.animation | F.audio | F.document)
async def wizard_media(
    message: Message,
    state: FSMContext,
    stages: StageStorage,
    content: ContentStorage,
):
    """Мастер, шаг 3: админ прислал файл (фото/видео/аудио/документ) — сохранить как медиа."""
    data = await state.get_data()
    if data.get("ctype") != CONTENT_MEDIA:
        return

    # достать файл из сообщения
    kind = KIND_DOCUMENT
    file_obj = None
    name = None
    if message.photo:
        kind, file_obj = KIND_PHOTO, message.photo[-1]
        name = f"photo_{int(int(time.time()))}.jpg"
    elif message.video:
        kind, file_obj = KIND_VIDEO, message.video
        name = message.video.file_name or f"video_{int(int(time.time()))}.mp4"
    elif message.animation:
        kind, file_obj = KIND_VIDEO, message.animation
        name = message.animation.file_name or f"animation_{int(int(time.time()))}.mp4"
    elif message.audio:
        kind, file_obj = KIND_AUDIO, message.audio
        name = message.audio.file_name or f"audio_{int(int(time.time()))}.mp3"
    elif message.document:
        file_obj = message.document
        name = message.document.file_name or f"file_{int(int(time.time()))}"
        kind = guess_kind(name, message.document.mime_type or "")
    if file_obj is None:
        await message.answer("Не распознал файл. Отправьте фото, видео, аудио или документ, или /cancel.")
        return

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as tmp:
            tmp_path = tmp.name
        await message.bot.download(file_obj, destination=tmp_path)
        media = content.add_media(tmp_path, name, kind)
    except Exception:
        log.exception("Не удалось скачать файл для медиа-этапа")
        await message.answer("Не удалось сохранить файл. Попробуйте ещё раз, или /cancel.")
        return
    finally:
        try:
            import os as _os
            _os.unlink(tmp_path)
        except (OSError, UnboundLocalError):
            pass

    if data.get("mode") == "edit" and stages.get(data.get("stage_id", -1)) is not None:
        stages.update(data["stage_id"], delay_seconds=data.get("delay", 0), content_type=CONTENT_MEDIA, content=str(media.id))
        await message.answer(f"✅ Файл сохранён: {media.name}. Этап обновлён. Текущий список:")
    else:
        stages.add(data.get("delay", 0), CONTENT_MEDIA, str(media.id))
        await message.answer(f"✅ Файл сохранён: {media.name}. Этап добавлен. Список:")

    await state.clear()
    text, kb = render_stages(stages, content)
    await message.answer(text, reply_markup=kb)


# --------------------- кнопки меню и списка ---------------------

@router.callback_query(F.data == "menu:stages")
async def cb_stages(cb: CallbackQuery, admin: AdminService, stages: StageStorage, content: ContentStorage):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    await cb.answer()
    text, kb = render_stages(stages, content)
    await answer_cb(cb, text, kb)


@router.callback_query(F.data == "menu:help")
async def cb_help(cb: CallbackQuery, admin: AdminService):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    await cb.answer()
    await answer_cb(cb, HELP_TEXT)


@router.callback_query(F.data == "wizard:add")
async def cb_wizard_add(cb: CallbackQuery, state: FSMContext, admin: AdminService):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    await cb.answer()
    if cb.message is not None:
        await start_wizard(cb.message, None, None, state)


@router.callback_query(F.data.startswith("wizard:edit:"))
async def cb_wizard_edit(
    cb: CallbackQuery,
    state: FSMContext,
    admin: AdminService,
    stages: StageStorage,
):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    stage_id = int(cb.data.rsplit(":", 1)[1])
    stage = stages.get(stage_id)
    if stage is None:
        await cb.answer("Этап не найден", show_alert=True)
        return
    await cb.answer()
    if cb.message is not None:
        await start_wizard(cb.message, stage, stages.index_of(stage) + 1, state)


@router.callback_query(F.data == "wizard:cancel")
async def cb_wizard_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")


@router.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery, admin: AdminService, stages: StageStorage, content: ContentStorage):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    stage_id = int(cb.data.split(":")[1])
    if stages.remove(stage_id):
        await cb.answer("Этап удалён")
    else:
        await cb.answer("Этап не найден", show_alert=True)
    text, kb = render_stages(stages, content)
    await answer_cb(cb, text, kb)


@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(cb: CallbackQuery, admin: AdminService, stages: StageStorage, content: ContentStorage):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    stage_id = int(cb.data.split(":")[1])
    stage = stages.toggle(stage_id)
    if stage is None:
        await cb.answer("Этап не найден", show_alert=True)
        return
    await cb.answer("Включён" if stage.enabled else "Выключен")
    text, kb = render_stages(stages, content)
    await answer_cb(cb, text, kb)


@router.callback_query(F.data.startswith("move:"))
async def cb_move(cb: CallbackQuery, admin: AdminService, stages: StageStorage, content: ContentStorage):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    _, stage_id, direction = cb.data.split(":")
    moved = stages.move(int(stage_id), -1 if direction == "-1" else 1)
    await cb.answer("Перемещён" if moved else "Дальше двигать нельзя")
    if moved:
        text, kb = render_stages(stages, content)
        await answer_cb(cb, text, kb)


@router.callback_query(F.data == "test:fast")
async def cb_test_fast(cb: CallbackQuery, admin: AdminService, stages: StageStorage, bot: Bot):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    await cb.answer("Запускаю тест")
    await run_test(bot, cb.message.chat.id if cb.message else cb.from_user.id, stages, live=False)


@router.callback_query(F.data == "test:live")
async def cb_test_live(cb: CallbackQuery, admin: AdminService, stages: StageStorage, bot: Bot):
    if not _cb_admin_ok(cb, admin):
        await _deny_cb(cb)
        return
    await cb.answer("Запускаю тест с задержками")
    await run_test(bot, cb.message.chat.id if cb.message else cb.from_user.id, stages, live=True)


# ----------------- текст админа вне мастера -----------------

@router.message(IsAdmin(), F.text & ~F.text.startswith("/"), StateFilter(None))
async def admin_text(message: Message):
    # Для не-админов этот обработчик не срабатывает (фильтр IsAdmin) —
    # событие дойдёт до клиентского обработчика, который подскажет /start.
    if message.chat.type != "private":
        return
    await message.answer("Для управления ботом используйте /admin 🙂")
