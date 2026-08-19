"""ПРОЦЕСС 2: веб-админ-панель (отдельно от бота).

FastAPI-сервер на порту WEB_PORT: настройка этапов, тест сценария.
Пишет в тот же bot_data/stages.json, что читает бот — изменения
подхватываются ботом мгновенно (он перечитывает файл перед отправкой).

Работает без доступа к Telegram: даже если бот «завис» или сеть к
Telegram отбита — админка открывается в браузере как обычно.

Запуск:  python admin.py
Лог:     bot_data/admin.log
Панель:  http://localhost:<WEB_PORT>
"""
from __future__ import annotations

import asyncio
import logging
import time

from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from app_common import setup
from config import Config
from web_panel import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("admin")


async def main() -> None:
    cfg = Config.from_env()
    storage, admin, sequencer, bot, content = setup(cfg, log_name="admin.log")

    app = create_app(
        cfg=cfg,
        storage=storage,
        content=content,
        bot=bot,
        sequencer=sequencer,
        admin=admin,
        started_at=time.time(),
    )

    log.info("Веб-админка запущена: http://localhost:%d", cfg.web_port)
    server = UvicornServer(
        UvicornConfig(app, host="0.0.0.0", port=cfg.web_port, log_level="warning")
    )
    await server.serve()


if __name__ == "__main__":
    Config.from_env()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановка веб-админки")
    except SystemExit:
        raise
    except Exception:
        log.exception("Веб-админка упала с ошибкой")
        print()
        print("!!! ADMIN PANEL CRASHED. Full details: bot_data\\admin.log")
        print()
        raise
