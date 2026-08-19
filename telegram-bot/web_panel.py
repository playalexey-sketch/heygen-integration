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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from sender import StageSequencer, run_test
from services import AdminService
from storage import CONTENT_LINK, CONTENT_NICKNAME, CONTENT_TEXT, CONTENT_TYPES, StageStorage

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
        return {
            "bot": f"@{username}" if username else None,
            "stages_total": len(storage.all()),
            "stages_enabled": len(storage.ordered()),
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

        if not live:
            # Быстрый тест — выполняем сразу и честно сообщаем результат,
            # в т.ч. «нет связи с Telegram».
            try:
                await run_test(bot, chat_id, storage, live=False)
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
                await run_test(bot, chat_id, storage, live=True)
            except Exception:
                log.exception("Тест сценария в чат %s не удался (см. admin.log)", chat_id)

        asyncio.create_task(_run())
        return {"ok": True, "live": True}

    # --- страница ---

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
