"""Веб-панель администратора (FastAPI) — ТОЛЬКО ОТОБРАЖЕНИЕ.

Все управление идёт из Telegram (команды бота: /rules, /addrule, /media,
/upmedia, /proxy, /setproxy, /crm, /mail, /admin и др.).
Веб-панель показывает актуальное состояние: этапы, медиа, правила со ссылками,
CRM клиентов, подключение. Данные читаются с диска в реальном времени —
что изменилось в Telegram, тут видно сразу.

Запускается отдельным процессом: python admin.py
"""
from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from typing import Optional

from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app_common import load_proxy
from content import KIND_ICONS, ContentStorage
from crm import CrmStorage
from sender import StageSequencer
from services import AdminService
from storage import StageStorage

log = logging.getLogger("web")

SESSION_TTL = 12 * 3600  # 12 часов

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
    content: ContentStorage,
    crm: CrmStorage,
    bot: Bot,
    sequencer: StageSequencer,
    admin: AdminService,
    started_at: float,
) -> FastAPI:
    app = FastAPI(title="TG Stage Bot — Admin (только просмотр)", docs_url=None, redoc_url=None)
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
        username = app.state.bot_username
        if not username:
            try:
                me = await bot.me()
                app.state.bot_username = username = me.username
            except Exception:
                username = None
        content.reload()
        crm.reload()
        return {
            "bot": f"@{username}" if username else None,
            "stages_total": len(storage.all()),
            "stages_enabled": len(storage.ordered()),
            "media_total": len(content.all_media()),
            "rules_total": len(content.all_rules()),
            "crm_total": len(crm.all()),
            "uptime_sec": int(time.time() - started_at),
            "web_password_set": bool(cfg.web_password),
        }

    # --- этапы (только чтение) ---

    @app.get("/api/stages")
    async def get_stages(request: Request):
        _auth(request)
        storage.reload()
        content.reload()
        out = []
        for i, s in enumerate(storage.all(), 1):
            d = {
                "position": i,
                "id": s.id,
                "enabled": s.enabled,
                "delay_seconds": s.delay_seconds,
                "content_type": s.content_type,
                "content": s.content,
                "media_name": None,
            }
            if s.content_type == "media":
                m = content.get_media(s.content)
                d["media_name"] = m.name if m else None
            out.append(d)
        return {"stages": out}

    # --- прокси (только чтение) ---

    @app.get("/api/proxy")
    async def get_proxy(request: Request):
        _auth(request)
        return {
            "proxy": load_proxy(cfg),
            "env_proxy": cfg.telegram_proxy,
            "note": "Управление прокси — командой /setproxy в Telegram",
        }

    # --- медиа (только чтение) ---

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

    # --- правила (только чтение) ---

    @app.get("/api/rules")
    async def get_rules(request: Request):
        _auth(request)
        content.reload()
        username = app.state.bot_username
        if not username:
            try:
                me = await bot.me()
                app.state.bot_username = username = me.username
            except Exception:
                username = "имя_вашего_бота"
        out = []
        for i, r in enumerate(content.all_rules(), 1):
            out.append({
                "position": i,
                "id": r.id,
                "trigger": r.trigger,
                "match": r.match,
                "content_type": r.content_type,
                "content": r.content,
                "enabled": r.enabled,
                "link": f"https://t.me/{username}?start={r.trigger}",
            })
        return {"rules": out, "bot": f"@{username}"}

    # --- CRM (только чтение) ---

    @app.get("/api/crm")
    async def get_crm(request: Request):
        _auth(request)
        crm.reload()
        clients = crm.all()
        return {
            "total": len(clients),
            "sources": crm.sources_stats(),
            "tags": crm.tags_stats(),
            "clients": [
                {
                    "id": u.id,
                    "username": u.username,
                    "name": " ".join(x for x in [u.first_name, u.last_name] if x),
                    "source": u.source,
                    "tags": u.tags,
                    "first_seen": u.first_seen,
                    "last_seen": u.last_seen,
                    "msgs": u.msgs,
                    "blocked": u.blocked,
                }
                for u in clients[:500]
            ],
        }

    # --- страница ---

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
