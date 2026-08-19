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

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError

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

    bot = Bot(token=cfg.bot_token)
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
            "Не удалось выполнить getMe (возможно, нет сети) — продолжаю, polling сам будет повторять запросы"
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

    # start_polling сам открывает/закрывает сессию бота при старте и стопе.
    await dp.start_polling(bot)


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
