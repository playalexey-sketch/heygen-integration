"""Телеграм-бот с веб-панелью администратора.

Один процесс, две вещи:
  1. бот: polling Telegram, проигрывает этапы клиенту после /start;
  2. веб-панель: http://<сервер>:<WEB_PORT> — настройка этапов в браузере
     (работает без VPN и без доступа к Telegram — просто браузер).

Запуск:
    cp .env.example .env      # вписать BOT_TOKEN, при желании ADMIN_PASSWORD
    python main.py
Или Docker:
    docker compose up -d --build
"""
from __future__ import annotations

import asyncio
import logging
import socket
import time

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from config import Config
from handlers.admin import router as admin_router
from handlers.client import router as client_router
from sender import StageSequencer
from services import AdminService
from storage import StageStorage
from web_panel import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


class IPv4AiohttpSession(AiohttpSession):
    """Сессия с принудительным IPv4.

    На части Windows-машин IPv6 к api.telegram.org «зависает» и даёт ошибку
    ClientConnectorError [Превышен таймаут семафора]. IPv4 это обходит.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init.setdefault("family", socket.AF_INET)


async def poll_forever(bot: Bot, dp: Dispatcher) -> None:
    """Polling с переподключением: обрыв сети не убивает бота."""
    while True:
        try:
            # handle_signals=False: сигналы (Ctrl+C) обрабатывает uvicorn
            await dp.start_polling(bot, handle_signals=False)
            return  # polling остановлен штатно (shutdown)
        except TelegramNetworkError:
            log.error("Сеть недоступна — бот ЖИВ, переподключение через 15 секунд")
            await asyncio.sleep(15)


async def main() -> None:
    cfg = Config.from_env()

    # Все логи дублируем в файл bot_data/bot.log — удобно при ошибках.
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(cfg.data_dir / "bot.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(file_handler)

    storage = StageStorage(cfg.stages_path)
    admin = AdminService(cfg.admin_ids)
    sequencer = StageSequencer(storage)
    bot = Bot(token=cfg.bot_token, session=IPv4AiohttpSession())

    # Данные передаются в обработчики по именам параметров (workflow data).
    dp = Dispatcher(stages=storage, admin=admin, sequencer=sequencer)
    dp.include_router(admin_router)   # командная /admin — остаётся работать и в Telegram
    dp.include_router(client_router)

    started_at = time.time()
    web_app = create_app(
        cfg=cfg,
        storage=storage,
        bot=bot,
        sequencer=sequencer,
        admin=admin,
        started_at=started_at,
    )

    log.info(
        "Этапов: %d (включено: %d). Файл данных: %s",
        len(storage.all()),
        len(storage.ordered()),
        cfg.stages_path,
    )
    log.info("Веб-панель: http://localhost:%d  (с других машин — http://<IP сервера>:%d)",
             cfg.web_port, cfg.web_port)
    if not cfg.admin_ids:
        log.warning(
            "ADMIN_ID не задан: в Telegram первым админом станет тот, кто пришлёт /admin. "
            "Веб-панель защищена паролем (ADMIN_PASSWORD или bot_data/admin_password.txt)."
        )

    try:
        me = await bot.me()
        log.info("Бот @%s подключён к Telegram", me.username)
    except TelegramUnauthorizedError:
        raise SystemExit(
            "Неверный BOT_TOKEN: Telegram вернул Unauthorized.\n"
            "Проверьте токен в .env (у @BotFather можно перевыпустить: /token)."
        )
    except Exception:
        log.warning(
            "getMe не удалось: нет сети, или VPN/антивирус блокирует api.telegram.org. "
            "Продолжаю — polling будет повторять запросы."
        )

    # Веб-сервер — основной цикл (корректно обрабатывает Ctrl+C и SIGTERM),
    # polling Telegram идёт фоном отдельной задачей.
    polling_task = asyncio.create_task(poll_forever(bot, dp), name="bot-polling")
    server = UvicornServer(
        UvicornConfig(web_app, host="0.0.0.0", port=cfg.web_port, log_level="warning")
    )
    try:
        await server.serve()
    finally:
        if polling_task and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except (asyncio.CancelledError, Exception):
                pass


if __name__ == "__main__":
    # Проверяем токен заранее: при ошибке сразу показываем понятное сообщение.
    Config.from_env()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановка бота")
    except SystemExit:
        raise
    except Exception:
        log.exception("Бот упал с ошибкой")
        print()
        print("!!! BOT CRASHED. Full details in the log file:")
        print("    bot_data\\bot.log")
        print()
        raise
