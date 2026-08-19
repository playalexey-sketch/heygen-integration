"""Управление из Telegram: правила/ссылки, медиа, прокси, CRM и рассылки.

Веб-панель — только отображение; все изменения делаются здесь, в чате с ботом.
"""
from __future__ import annotations

import asyncio
import re
import tempfile
import time
import urllib.parse
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app_common import apply_proxy, load_proxy
from content import KIND_AUDIO, KIND_DOCUMENT, KIND_PHOTO, KIND_VIDEO, ContentStorage, guess_kind
from crm import CrmStorage
from services import AdminService
from storage import CONTENT_LINK, CONTENT_MEDIA, CONTENT_NICKNAME, StageStorage

from .admin import guard_admin

router = Router(name="manager")

SOCIAL_SOURCES = ("youtube", "vk", "instagram", "tiktok")

MAX_DELAY = 24 * 3600
MAIL_DELAY = 0.15  # сек между письмами рассылки (безопасный темп)
mailing_active: set = set()  # id чата админа, у которого уже идёт рассылка


# ----------------------------- FSM -----------------------------

class RuleWizard(StatesGroup):
    trigger = State()
    match = State()
    ctype = State()
    content = State()


class UploadMedia(StatesGroup):
    waiting = State()


# ----------------------------- помощники -----------------------------

async def _bot_username(bot: Bot) -> str:
    try:
        me = await bot.me()  # кешируется после первого getMe (при старте)
        return me.username or "имя_вашего_бота"
    except Exception:
        return "имя_вашего_бота"


async def _bot_link(bot: Bot, trigger: str) -> str:
    name = await _bot_username(bot)
    return f"https://t.me/{name}?start={urllib.parse.quote(trigger, safe='')}"


def _rule_line(i: int, r, link: str) -> str:
    icon = {"text": "📄", "link": "🔗", "nickname": "👤", "media": "🎬"}.get(r.content_type, "•")
    status = "✅" if r.enabled else "⏸"
    mode = "точно" if r.match == "exact" else "содержит"
    if r.content_type == "media":
        return (
            f"{i}. {status} [{r.trigger}] ({mode}) {icon} файл #{r.content}\n"
            f"    ссылка: {link}"
        )
    preview = " ".join(r.content.split())
    if len(preview) > 60:
        preview = preview[:57] + "…"
    return (
        f"{i}. {status} [{r.trigger}] ({mode}) {icon} «{preview}»\n"
        f"    ссылка: {link}"
    )


async def _render_rules(content: ContentStorage, bot: Bot) -> str:
    rules = content.all_rules()
    username = await _bot_username(bot)
    lines = ["🔑 Ключевые слова (сверху вниз — по приоритету):", ""]
    if rules:
        for i, r in enumerate(rules, 1):
            link = f"https://t.me/{username}?start={urllib.parse.quote(r.trigger, safe='')}"
            lines.append(_rule_line(i, r, link))
    else:
        lines.append("Правил пока нет. Добавить: /addrule")
    lines += [
        "",
        "🌐 Готовые ссылки для соцсетей (вставьте в описание видео / пост / шапку профиля):",
    ]
    for src in SOCIAL_SOURCES:
        lines.append(f"  {src:10} https://t.me/{username}?start={src}")
    lines += [
        "",
        "Клиент по ссылке попадает в бота: получает этапы + контент по коду,",
        "и попадает в CRM с меткой, откуда пришёл (/crm).",
        "",
        "Команды: /addrule — добавить, /delrule N — удалить,",
        "/onrule N, /offrule N — вкл/выкл.",
    ]
    return "\n".join(lines)


async def _download_and_store(message: Message, content: ContentStorage, name_hint: str | None = None):
    """Скачать файл из сообщения админа и сохранить как медиа. Возвращает Media."""
    kind = KIND_DOCUMENT
    file_obj = None
    name = name_hint
    if message.photo:
        kind, file_obj = KIND_PHOTO, message.photo[-1]
        name = name or f"photo_{int(time.time())}.jpg"
    elif message.video:
        kind, file_obj = KIND_VIDEO, message.video
        name = name or message.video.file_name or f"video_{int(time.time())}.mp4"
    elif message.animation:
        kind, file_obj = KIND_VIDEO, message.animation
        name = name or message.animation.file_name or f"animation_{int(time.time())}.mp4"
    elif message.audio:
        kind, file_obj = KIND_AUDIO, message.audio
        name = name or message.audio.file_name or f"audio_{int(time.time())}.mp3"
    elif message.document:
        file_obj = message.document
        name = name or message.document.file_name or f"file_{int(time.time())}"
        kind = guess_kind(name, message.document.mime_type or "")
    if file_obj is None:
        return None
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name or "file").suffix) as tmp:
        tmp_path = tmp.name
    try:
        await message.bot.download(file_obj, destination=tmp_path)
        return content.add_media(tmp_path, name or "file", kind)
    finally:
        try:
            import os
            os.unlink(tmp_path)
        except OSError:
            pass


async def _do_mailing(bot: Bot, crm: CrmStorage, targets, text: str, report_chat: int) -> None:
    ok = failed = skipped = 0
    for rec in targets:
        if rec.blocked:
            skipped += 1
            continue
        try:
            await bot.send_message(rec.id, text)
            ok += 1
        except TelegramForbiddenError:
            crm.mark_blocked(rec.id)
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(MAIL_DELAY)
    try:
        await bot.send_message(
            report_chat,
            f"✅ Рассылка завершена: доставлено {ok}, сбоев {failed}, "
            f"пропущено (заблокировали) {skipped}. Всего адресатов: {len(targets)}.",
        )
    except Exception:
        pass


# ----------------------------- правила / ссылки -----------------------------

@router.message(Command("rules"))
async def cmd_rules(message: Message, admin: AdminService, content: ContentStorage):
    if not await guard_admin(message, admin):
        return
    content.reload()
    await message.answer(await _render_rules(content, message.bot))


@router.message(Command("addrule"))
async def cmd_addrule(message: Message, state: FSMContext, admin: AdminService):
    if not await guard_admin(message, admin):
        return
    await state.set_state(RuleWizard.trigger.state)
    await state.update_data(mode="add")
    await message.answer(
        "➕ Новое правило. Шаг 1/4 — отправьте ТРИГГЕР: слово, символ, код или цифру, "
        "по которой сработает правило (например: 123, #promo, video). Или /cancel."
    )


@router.message(RuleWizard.trigger, F.text)
async def rule_w_trigger(message: Message, state: FSMContext):
    trigger = (message.text or "").strip()
    if not trigger:
        await message.answer("Триггер не может быть пустым. Пришлите его ещё раз, или /cancel.")
        return
    await state.update_data(trigger=trigger)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Точное совпадение", callback_data="rmatch:exact")],
            [InlineKeyboardButton(text="Вход содержит триггер", callback_data="rmatch:contains")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="rwizard:cancel")],
        ]
    )
    await message.answer(
        f"Триггер: [{trigger}]\nШаг 2/4 — режим совпадения:", reply_markup=kb
    )
    await state.set_state(RuleWizard.match.state)


@router.callback_query(RuleWizard.match, F.data.startswith("rmatch:"))
async def rule_w_match(cb, state: FSMContext):
    match = cb.data.split(":", 1)[1]
    await state.update_data(match=match)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Текст", callback_data="rtype:text")],
            [InlineKeyboardButton(text="🔗 Ссылка", callback_data="rtype:link")],
            [InlineKeyboardButton(text="👤 Ник", callback_data="rtype:nickname")],
            [InlineKeyboardButton(text="🎬 Медиа-файл", callback_data="rtype:media")],
        ]
    )
    await cb.answer()
    await cb.message.answer("Шаг 3/4 — что отправлять клиенту?", reply_markup=kb)
    await state.set_state(RuleWizard.ctype.state)


@router.callback_query(RuleWizard.ctype, F.data.startswith("rtype:"))
async def rule_w_ctype(cb, state: FSMContext):
    ctype = cb.data.split(":", 1)[1]
    await state.update_data(ctype=ctype)
    prompts = {
        "text": "Шаг 4/4 — отправьте ТЕКСТ ответа обычным сообщением.",
        "link": "Шаг 4/4 — отправьте ссылку (https://...), которую получит клиент.",
        "nickname": "Шаг 4/4 — отправьте ник: @username.",
        "media": "Шаг 4/4 — отправьте сам файл (фото/видео/аудио/любой файл), я сохраню его в боте.",
    }
    await cb.answer()
    await cb.message.answer(prompts.get(ctype, "Шаг 4/4 — отправьте контент."))
    await state.set_state(RuleWizard.content.state)


@router.message(RuleWizard.content, F.text)
async def rule_w_content(message: Message, state: FSMContext, content: ContentStorage):
    data = await state.get_data()
    ctype = data.get("ctype", "text")
    raw = (message.text or "").strip()
    if ctype == "link":
        if not re.fullmatch(r"https?://\S+", raw):
            await message.answer("Это не похоже на ссылку. Пришлите https://... или /cancel.")
            return
    elif ctype == "nickname":
        u = raw.lstrip("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", u):
            await message.answer("Ник: @username (5–32 символа). Пришлите ещё раз, или /cancel.")
            return
    else:
        if not raw:
            await message.answer("Текст не может быть пустым.")
            return
    r = content.add_rule(data.get("trigger", ""), ctype, raw, data.get("match", "exact"))
    await state.clear()
    await message.answer(
        f"✅ Правило добавлено: [{r.trigger}] → {ctype}\n"
        f"Ссылка для клиентов: {await _bot_link(message.bot, r.trigger)}"
    )
    await message.answer(await _render_rules(content, message.bot))


@router.message(RuleWizard.content, F.photo | F.video | F.animation | F.audio | F.document)
async def rule_w_media(message: Message, state: FSMContext, content: ContentStorage):
    data = await state.get_data()
    if data.get("ctype") != "media":
        return
    media = await _download_and_store(message, content)
    if media is None:
        await message.answer("Не распознал файл. Отправьте фото/видео/аудио/документ, или /cancel.")
        return
    r = content.add_rule(data.get("trigger", ""), "media", str(media.id), data.get("match", "exact"))
    await state.clear()
    await message.answer(
        f"✅ Файл сохранён: {media.name}\n"
        f"Правило добавлено: [{r.trigger}] → 🎬 {media.name}\n"
        f"Ссылка для клиентов: {await _bot_link(message.bot, r.trigger)}"
    )
    await message.answer(await _render_rules(content, message.bot))


@router.callback_query(F.data == "rwizard:cancel")
async def rwizard_cancel(cb, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")


def _rule_by_pos(content: ContentStorage, message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return None


@router.message(Command("delrule"))
async def cmd_delrule(message: Message, admin: AdminService, content: ContentStorage):
    if not await guard_admin(message, admin):
        return
    n = _rule_by_pos(content, message)
    r = content.get_by_position(n) if n else None
    if r is None:
        await message.answer("Укажите номер: /delrule N (список — /rules)")
        return
    content.remove_rule(r.id)
    await message.answer(f"🗑 Правило {n} ([{r.trigger}]) удалено.\n\n{await _render_rules(content, message.bot)}")


@router.message(Command("onrule"))
async def cmd_onrule(message: Message, admin: AdminService, content: ContentStorage):
    await _set_rule_enabled(message, admin, content, True)


@router.message(Command("offrule"))
async def cmd_offrule(message: Message, admin: AdminService, content: ContentStorage):
    await _set_rule_enabled(message, admin, content, False)


async def _set_rule_enabled(message: Message, admin: AdminService, content: ContentStorage, value: bool):
    if not await guard_admin(message, admin):
        return
    n = _rule_by_pos(content, message)
    r = content.get_by_position(n) if n else None
    if r is None:
        await message.answer(f"Укажите номер: /{'on' if value else 'off'}rule N (список — /rules)")
        return
    content.set_enabled(r.id, value)
    await message.answer(f"Правило {n} ({'включено' if value else 'выключено'}).\n\n{await _render_rules(content, message.bot)}")


# ----------------------------- медиа -----------------------------

@router.message(Command("media"))
async def cmd_media(message: Message, admin: AdminService, content: ContentStorage):
    if not await guard_admin(message, admin):
        return
    content.reload()
    media = content.all_media()
    if not media:
        await message.answer("🎬 Медиа-файлов пока нет. Загрузить: /upmedia")
        return
    from content import KIND_ICONS
    lines = ["🎬 Медиа-файлы бота:", ""]
    for m in media:
        size = f"{m.size / 1048576:.1f} МБ" if m.size > 1048576 else f"{m.size // 1024} КБ"
        lines.append(f"  #{m.id} {KIND_ICONS.get(m.kind, '📎')} {m.name} ({size})")
    lines += ["", "Загрузить новый файл: /upmedia"]
    await message.answer("\n".join(lines))


@router.message(Command("upmedia"))
async def cmd_upmedia(message: Message, state: FSMContext, admin: AdminService):
    if not await guard_admin(message, admin):
        return
    await state.set_state(UploadMedia.waiting.state)
    await message.answer("Отправьте файл (фото/видео/аудио/любой файл) следующим сообщением, или /cancel.")


@router.message(UploadMedia.waiting, F.photo | F.video | F.animation | F.audio | F.document)
async def upmedia_file(message: Message, state: FSMContext, content: ContentStorage):
    media = await _download_and_store(message, content)
    await state.clear()
    if media is None:
        await message.answer("Не распознал файл. Попробуйте ещё раз: /upmedia")
        return
    from content import KIND_ICONS
    await message.answer(f"✅ Сохранено: #{media.id} {KIND_ICONS.get(media.kind, '📎')} {media.name}")
    await message.answer("Теперь его можно выбрать в этапе (/add → 🎬 Медиа) или в правиле (/addrule).")


# ----------------------------- прокси -----------------------------

@router.message(Command("proxy"))
async def cmd_proxy(message: Message, admin: AdminService, cfg):
    if not await guard_admin(message, admin):
        return
    p = load_proxy(cfg)
    await message.answer("🔌 Текущий прокси Telegram-подключения:\n" + (p or "(прямое соединение)"))


@router.message(Command("setproxy"))
async def cmd_setproxy(message: Message, admin: AdminService, cfg):
    if not await guard_admin(message, admin):
        return
    parts = (message.text or "").split(maxsplit=1)
    proxy = parts[1].strip() if len(parts) > 1 else ""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.proxy_path.write_text(proxy + "\n", encoding="utf-8")
    apply_proxy(message.bot, proxy)
    await message.answer(
        "🔌 Прокси обновлён: " + (proxy or "(прямое соединение)") + "\n"
        "Бот применит его при следующем переподключении (≈15 сек)."
    )


# ----------------------------- CRM -----------------------------

def _fmt_client(i: int, u) -> str:
    name = " ".join(x for x in [u.first_name, u.last_name] if x) or "—"
    nick = f"@{u.username}" if u.username else str(u.id)
    src = f" | из: {u.source}" if u.source else ""
    tags = f" | #{' #'.join(u.tags)}" if u.tags else ""
    blocked = " | ⛔ заблокировал" if u.blocked else ""
    return f"{i}. {nick} — {name}{src}{tags}{blocked} (был: {u.last_seen})"


@router.message(Command("crm"))
async def cmd_crm(message: Message, admin: AdminService, crm: CrmStorage):
    if not await guard_admin(message, admin):
        return
    crm.reload()
    clients = crm.all()
    if not clients:
        await message.answer("👥 CRM пуста — клиентов ещё не было.")
        return
    lines = [f"👥 CRM: клиентов {len(clients)}", ""]
    ss = crm.sources_stats()
    if ss:
        lines.append("По источникам: " + ", ".join(f"{k}: {v}" for k, v in ss.items()))
    ts = crm.tags_stats()
    if ts:
        lines.append("По тегам: " + ", ".join(f"#{k}: {v}" for k, v in ts.items()))
    lines += ["", "Последние активные:"]
    for i, u in enumerate(clients[:15], 1):
        lines.append(_fmt_client(i, u))
    lines += [
        "",
        "Теги: /tag <ID> <тег>, /untag <ID> <тег>",
        "Рассылка: /mail all <текст> | /mail tag:<тег> <текст> | /mail src:<источник> <текст>",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("tag"))
async def cmd_tag(message: Message, admin: AdminService, crm: CrmStorage):
    if not await guard_admin(message, admin):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Формат: /tag <ID клиента> <тег>. ID видны в /crm.")
        return
    crm.reload()
    rec = crm.add_tag(parts[1], parts[2])
    if rec is None:
        await message.answer("Клиент не найден (ID из /crm).")
    else:
        await message.answer(f"✅ Тег #{rec.tags[-1]} добавлен: {rec.id}")


@router.message(Command("untag"))
async def cmd_untag(message: Message, admin: AdminService, crm: CrmStorage):
    if not await guard_admin(message, admin):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Формат: /untag <ID клиента> <тег>.")
        return
    crm.reload()
    rec = crm.remove_tag(parts[1], parts[2])
    if rec is None:
        await message.answer("Клиент не найден.")
    else:
        await message.answer(f"Тег снят. Осталось: {', '.join(rec.tags) or '—'}")


# ----------------------------- рассылки -----------------------------

@router.message(Command("mail"))
async def cmd_mail(message: Message, admin: AdminService, crm: CrmStorage):
    if not await guard_admin(message, admin):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[2].strip():
        await message.answer(
            "Форматы рассылки:\n"
            "/mail all <текст> — всем клиентам\n"
            "/mail tag:<тег> <текст> — по тегу\n"
            "/mail src:<источник> <текст> — по источнику (youtube, vk, ...)"
        )
        return
    selector, text = parts[1], parts[2]
    crm.reload()
    if selector == "all":
        targets = crm.all()
    elif selector.startswith("tag:"):
        targets = crm.by_tag(selector[4:])
    elif selector.startswith("src:"):
        targets = crm.by_source(selector[4:])
    else:
        await message.answer("Не понял выборку. Варианты: all, tag:<тег>, src:<источник>.")
        return
    if not targets:
        await message.answer("Под эту выборку нет клиентов.")
        return
    if message.chat.id in mailing_active:
        await message.answer("⏳ Уже идёт рассылка — дождитесь отчёта.")
        return
    mailing_active.add(message.chat.id)
    asyncio.create_task(_run_mailing(message.bot, crm, targets, text, message.chat.id))
    await message.answer(
        f"📤 Рассылка запущена: {len(targets)} получателей. Отчёт придёт сюда."
    )


async def _run_mailing(bot: Bot, crm: CrmStorage, targets, text: str, report_chat: int) -> None:
    try:
        await _do_mailing(bot, crm, targets, text, report_chat)
    except Exception:
        import logging
        logging.getLogger("manager").exception("Рассылка упала")
    finally:
        mailing_active.discard(report_chat)
