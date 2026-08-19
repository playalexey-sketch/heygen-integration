"""Веб-панель администратора (FastAPI). Запускается отдельным процессом: python admin.py.

Даёт весь функционал, который есть в командной /admin:
этапы (добавить/редактировать/порядок/вкл-выкл/удалить), тест сценария.
Настройки живут в том же stages.json, что и у бота — изменения
подхватываются ботом мгновенно, без перезапуска (бот перечитывает файл).
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import os
import tempfile

from app_common import IPv4AiohttpSession, apply_proxy, load_proxy
from content import KIND_ICONS, MATCH_CONTAINS, MATCH_EXACT, ContentStorage, guess_kind
from sender import StageSequencer, run_test
from services import AdminService
from storage import CONTENT_LINK, CONTENT_MEDIA, CONTENT_NICKNAME, CONTENT_TEXT, CONTENT_TYPES, StageStorage

log = logging.getLogger("web")

SESSION_TTL = 12 * 3600  # 12 часов
MAX_DELAY = 24 * 3600

STATIC_DIR = Path(__file__).parent / "static"


def _password(cfg) -> str:
    """Пароль панели: из .env; если пуст — генерируем один раз и сохраняем."""
    if cfg.web_password:
        return cfg.web_password
    if cfg.password_path.exists():
        return cfg.password_path.read_text(encoding="utf-8").strip()
    pw = secrets.token_urlsafe(6)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.password_path.write_text(pw + "\n", encoding="utf-8")
    log.warning(
        "ADMIN_PASSWORD не задан в .env — сгенерирован пароль: %s "
        "(сохранён в %s). Уберите его из лога и впишите в ADMIN_PASSWORD.",
        pw,
        cfg.password_path,
    )
    return pw


def create_app(
    cfg,
    storage: StageStorage,
    content: "ContentStorage",
    bot: Bot,
    sequencer: StageSequencer,
    admin: AdminService,
    started_at: float,
) -> FastAPI:
    app = FastAPI(title="TG Stage Bot — Admin", docs_url=None, redoc_url=None)
    app.state.sessions: dict[str, float] = {}
    app.state.bot_username: Optional[str] = None

    # --- auth ---

    def _auth(request: Request) -> None:
        token = request.cookies.get("session", "")
        exp = app.state.sessions.get(token)
        if not exp or exp < time.time():
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.post("/api/login")
    async def login(request: Request):
        body = await request.json()
        if body.get("password") == _password(cfg):
            token = secrets.token_urlsafe(16)
            app.state.sessions[token] = time.time() + SESSION_TTL
            resp = JSONResponse({"ok": True})
            resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=SESSION_TTL)
            return resp
        return JSONResponse({"ok": False, "error": "Неверный пароль"}, status_code=401)

    @app.post("/api/logout")
    async def logout(request: Request):
        token = request.cookies.get("session", "")
        app.state.sessions.pop(token, None)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("session")
        return resp

    # --- статус ---

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        # Статус не защищаем паролем: там нет чувствительных данных.
        username = app.state.bot_username
        if not username:
            try:
                me = await bot.me()
                app.state.bot_username = username = me.username
            except Exception:
                username = None
        content.reload()
        return {
            "bot": f"@{username}" if username else None,
            "stages_total": len(storage.all()),
            "stages_enabled": len(storage.ordered()),
            "media_total": len(content.all_media()),
            "rules_total": len(content.all_rules()),
            "uptime_sec": int(time.time() - started_at),
            "web_password_set": bool(cfg.web_password),
        }

    # --- этапы ---

    def _stage_dict(i: int, s) -> dict:
        return {
            "position": i,
            "id": s.id,
            "enabled": s.enabled,
            "delay_seconds": s.delay_seconds,
            "content_type": s.content_type,
            "content": s.content,
        }

    @app.get("/api/stages")
    async def get_stages(request: Request):
        _auth(request)
        storage.reload()  # актуальное состояние с диска (общий файл с ботом)
        return {"stages": [_stage_dict(i, s) for i, s in enumerate(storage.all(), 1)]}

    def content_storage_get_media(mid) -> object:
        content.reload()
        return content.get_media(mid)

    def _validate(delay_seconds, content_type: str, content: str) -> str:
        if not str(delay_seconds).lstrip("-").isdigit():
            raise HTTPException(400, "Задержка — целое число секунд (0 = сразу)")
        delay = int(delay_seconds)
        if delay < 0 or delay > MAX_DELAY:
            raise HTTPException(400, f"Задержка: от 0 до {MAX_DELAY} секунд")
        if content_type not in CONTENT_TYPES:
            raise HTTPException(400, "Неизвестный тип контента")
        content = (content or "").strip()
        if content_type == CONTENT_LINK:
            if not re.fullmatch(r"https?://\S+", content):
                raise HTTPException(400, "Ссылка должна начинаться с http:// или https://")
        elif content_type == CONTENT_NICKNAME:
            u = content.lstrip("@").strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", u):
                raise HTTPException(400, "Ник: @username, 5–32 символа (латиница, цифры, _)")
        elif content_type == CONTENT_MEDIA:
            if not content or content_storage_get_media(content) is None:
                raise HTTPException(400, "Выберите файл из списка медиа (вкладка «Медиа»)")
        else:
            if not content:
                raise HTTPException(400, "Текст не может быть пустым")
            content = (content or "").strip()
        return content

    @app.post("/api/stages")
    async def add_stage(request: Request):
        _auth(request)
        b = await request.json()
        content = _validate(b.get("delay_seconds", 0), b.get("content_type", CONTENT_TEXT), b.get("content", ""))
        s = storage.add(int(b.get("delay_seconds", 0)), b.get("content_type", CONTENT_TEXT), content)
        return _stage_dict(len(storage.all()), s)

    @app.patch("/api/stages/{stage_id}")
    async def update_stage(stage_id: int, request: Request):
        _auth(request)
        b = await request.json()
        current = storage.get(stage_id)
        if current is None:
            raise HTTPException(404, "Этап не найден")
        delay = b.get("delay_seconds", current.delay_seconds)
        ctype = b.get("content_type", current.content_type)
        content = _validate(delay, ctype, b.get("content", current.content))
        s = storage.update(stage_id, delay_seconds=int(delay), content_type=ctype, content=content)
        i = storage.index_of(s) + 1
        return _stage_dict(i, s)

    @app.delete("/api/stages/{stage_id}")
    async def delete_stage(stage_id: int, request: Request):
        _auth(request)
        if not storage.remove(stage_id):
            raise HTTPException(404, "Этап не найден")
        return {"ok": True}

    @app.post("/api/stages/{stage_id}/move")
    async def move_stage(stage_id: int, request: Request):
        _auth(request)
        b = await request.json()
        d = int(b.get("direction", 0))
        if d not in (-1, 1) or not storage.move(stage_id, d):
            raise HTTPException(400, "Дальше двигать нельзя")
        return {"ok": True}

    @app.post("/api/stages/{stage_id}/toggle")
    async def toggle_stage(stage_id: int, request: Request):
        _auth(request)
        s = storage.toggle(stage_id)
        if s is None:
            raise HTTPException(404, "Этап не найден")
        return _stage_dict(storage.index_of(s) + 1, s)

    # --- прокси / VPN (соединение с Telegram) ---

    async def _check(proxy: str) -> dict:
        """Проверка соединения с Telegram через указанный прокси (временная сессия)."""
        session = AiohttpSession(proxy=proxy) if proxy else IPv4AiohttpSession()
        tmp_bot = Bot(token=cfg.bot_token, session=session)
        try:
            me = await asyncio.wait_for(tmp_bot.me(), 15)
            return {"ok": True, "bot": f"@{me.username}", "via": proxy or "прямое соединение"}
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if "401" in msg or "Unauthorized" in msg:
                msg = "Соединение есть, но BOT_TOKEN неверный (401 Unauthorized)"
            return {"ok": False, "error": msg, "via": proxy or "прямое соединение"}
        finally:
            await session.close()

    @app.get("/api/proxy")
    async def get_proxy(request: Request):
        _auth(request)
        return {
            "proxy": load_proxy(cfg),
            "env_proxy": cfg.telegram_proxy,
            "file_exists": cfg.proxy_path.exists(),
        }

    @app.post("/api/proxy")
    async def set_proxy(request: Request):
        _auth(request)
        b = await request.json()
        proxy = (b.get("proxy") or "").strip()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cfg.proxy_path.write_text(proxy + "\n", encoding="utf-8")
        log.info("Прокси сохранён из панели: %r", proxy or "(прямое)")
        apply_proxy(bot, proxy)  # тест-отправки админки сразу пойдут через новый прокси
        result = await _check(proxy)
        return result

    @app.post("/api/check_telegram")
    async def check_telegram(request: Request):
        _auth(request)
        b = await request.json()
        raw = b.get("proxy")
        proxy = load_proxy(cfg) if raw is None else (raw or "").strip()
        return await _check(proxy)

    # --- тест ---

    @app.post("/api/test")
    async def test(request: Request):
        _auth(request)
        b = await request.json()
        try:
            chat_id = int(b.get("chat_id", 0))
        except (TypeError, ValueError):
            raise HTTPException(400, "chat_id — числовой ID чата")
        if chat_id <= 0:
            raise HTTPException(400, "chat_id — числовой ID чата")
        live = bool(b.get("live", False))
        apply_proxy(bot, load_proxy(cfg))

        if not live:
            # Быстрый тест — выполняем сразу и честно сообщаем результат,
            # в т.ч. «нет связи с Telegram».
            try:
                await run_test(bot, chat_id, storage, live=False, content_storage=content)
            except Exception as e:
                log.exception("Тест сценария в чат %s не удался", chat_id)
                msg = str(e)
                if "Cannot connect" in msg or "timeout" in msg.lower():
                    msg = (
                        "Не удалось отправить: нет соединения с Telegram "
                        "(машина, где запущен бот, не может достичь api.telegram.org — "
                        "блокировка/VPN). Панель работает, но сообщения доставит бот, "
                        "только запущенный на машине с доступом к Telegram."
                    )
                raise HTTPException(502, msg)
            return {"ok": True, "live": False}

        async def _run():
            try:
                await run_test(bot, chat_id, storage, live=True, content_storage=content)
            except Exception:
                log.exception("Тест сценария в чат %s не удался (см. admin.log)", chat_id)

        asyncio.create_task(_run())
        return {"ok": True, "live": True}

    # --- медиа ---

    @app.get("/api/media")
    async def get_media(request: Request):
        _auth(request)
        content.reload()
        return {"media": [
            {
                "id": m.id,
                "name": m.name,
                "kind": m.kind,
                "size": m.size,
                "icon": KIND_ICONS.get(m.kind, "📎"),
            }
            for m in content.all_media()
        ]}

    @app.post("/api/media")
    async def upload_media(request: Request, file: UploadFile = File(...)):
        _auth(request)
        name = file.filename or "file"
        kind = guess_kind(name, file.content_type or "")
        fd, tmp = tempfile.mkstemp(suffix=Path(name).suffix, prefix=".up-")
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    out.write(chunk)
            media = content.add_media(tmp, name, kind)
        except Exception:
            log.exception("Загрузка медиа не удалась")
            raise HTTPException(500, "Не удалось сохранить файл")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return {
            "id": media.id, "name": media.name, "kind": media.kind,
            "size": media.size, "icon": KIND_ICONS.get(media.kind, "📎"),
        }

    @app.delete("/api/media/{media_id}")
    async def delete_media(media_id: int, request: Request):
        _auth(request)
        if not content.remove_media(media_id):
            raise HTTPException(404, "Медиа не найдено")
        return {"ok": True}

    # --- правила (ключевые слова) ---

    def _rule_dict(i: int, r) -> dict:
        return {
            "position": i,
            "id": r.id,
            "trigger": r.trigger,
            "match": r.match,
            "content_type": r.content_type,
            "content": r.content,
            "enabled": r.enabled,
        }

    @app.get("/api/rules")
    async def get_rules(request: Request):
        _auth(request)
        content.reload()
        return {"rules": [_rule_dict(i, r) for i, r in enumerate(content.all_rules(), 1)]}

    @app.post("/api/rules")
    async def add_rule(request: Request):
        _auth(request)
        b = await request.json()
        trigger = (b.get("trigger") or "").strip()
        match = b.get("match") or MATCH_EXACT
        ctype = b.get("content_type", "text")
        if not trigger:
            raise HTTPException(400, "Триггер (слово/символ/код) не может быть пустым")
        if match not in (MATCH_EXACT, MATCH_CONTAINS):
            raise HTTPException(400, "match: exact или contains")
        c = _validate(0, ctype, b.get("content", ""))
        r = content.add_rule(trigger, ctype, c, match)
        return _rule_dict(len(content.all_rules()), r)

    @app.patch("/api/rules/{rule_id}")
    async def update_rule(rule_id: int, request: Request):
        _auth(request)
        b = await request.json()
        r0 = content.get_rule(rule_id)
        if r0 is None:
            raise HTTPException(404, "Правило не найдено")
        trigger = (b.get("trigger") or r0.trigger).strip()
        match = b.get("match") or r0.match
        ctype = b.get("content_type") or r0.content_type
        c = _validate(0, ctype, b.get("content", r0.content))
        r = content.update_rule(
            rule_id, trigger=trigger, match=match, content_type=ctype, content=c
        )
        return _rule_dict(content.index_of(r) + 1, r)

    @app.delete("/api/rules/{rule_id}")
    async def delete_rule(rule_id: int, request: Request):
        _auth(request)
        if not content.remove_rule(rule_id):
            raise HTTPException(404, "Правило не найдено")
        return {"ok": True}

    @app.post("/api/rules/{rule_id}/toggle")
    async def toggle_rule(rule_id: int, request: Request):
        _auth(request)
        r = content.toggle_rule(rule_id)
        if r is None:
            raise HTTPException(404, "Правило не найдено")
        return _rule_dict(content.index_of(r) + 1, r)

    @app.post("/api/rules/{rule_id}/move")
    async def move_rule(rule_id: int, request: Request):
        _auth(request)
        b = await request.json()
        d = int(b.get("direction", 0))
        if d not in (-1, 1) or not content.move_rule(rule_id, d):
            raise HTTPException(400, "Дальше двигать нельзя")
        return {"ok": True}

    # --- страница ---

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
