"""Телеграм-бот: последовательность этапов после /start + админ-панель.

Запуск:
    cp .env.example .env      # и вписать BOT_TOKEN
    python main.py

Или через Docker:
    docker compose up -d --build
"""
from __future__ import annotations

import asyncio
import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from config import Config
from handlers.admin import router as admin_router
from handlers.client import router as client_router
from sender import StageSequencer
from services import AdminService
from storage import StageStorage

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


async def main() -> None:
    cfg = Config.from_env()

    # Все логи дублируем в файл bot_data/bot.log — при ошибке его можно открыть и показать.
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
    try:
        me = await bot.me()
        log.info("Бот @%s запущен", me.username)
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
    log.info(
        "Этапов: %d (включено: %d). Файл данных: %s",
        len(storage.all()),
        len(storage.ordered()),
        cfg.stages_path,
    )
    if not cfg.admin_ids:
        log.warning(
            "ADMIN_ID не задан: первый, кто пришлёт /admin, станет админом. "
            "Лучше пропишите свой ID в .env."
        )

    # Данные передаются в обработчики по именам параметров (workflow data).
    dp = Dispatcher(stages=storage, admin=admin, sequencer=sequencer)
    dp.include_router(admin_router)   # сначала админ, затем клиент
    dp.include_router(client_router)

    # Polling: если сеть временно недоступна — бот не вылетает,
    # а ждёт и переподключается (внутри polling сам ретраит getUpdates).
    while True:
        try:
            # start_polling сам открывает/закрывает сессию бота при старте и стопе.
            await dp.start_polling(bot)
            return
        except TelegramNetworkError:
            log.error("Сеть недоступна — бот ЖИВ, переподключение через 15 секунд")
            await asyncio.sleep(15)


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
