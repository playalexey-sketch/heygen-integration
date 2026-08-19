"""ПРОЦЕСС 1: Telegram-бот.

Polling Telegram + проигрывание этапов клиенту после /start.
Настройки читает из bot_data/stages.json (общий файл с веб-админкой),
перед отправкой каждому клиенту перечитывает файл заново — поэтому
изменения из админки действуют мгновенно, без перезапуска.

Запуск:  python bot.py
Лог:     bot_data/bot.log
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError

from app_common import check_bot_online, setup
from config import Config
from handlers.admin import router as admin_router
from handlers.client import router as client_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")


async def poll_forever(bot: Bot, dp: Dispatcher) -> None:
    """Polling с переподключением: обрыв сети не убивает бота."""
    while True:
        try:
            # handle_signals=False: Ctrl+C обрабатывает run.bat (прерывает процесс).
            await dp.start_polling(bot, handle_signals=False)
            return  # polling остановлен штатно (shutdown)
        except TelegramNetworkError:
            log.error("Сеть недоступна — бот ЖИВ, переподключение через 15 секунд")
            await asyncio.sleep(15)


async def main() -> None:
    cfg = Config.from_env()
    storage, admin, sequencer, bot = setup(cfg, log_name="bot.log")

    dp = Dispatcher(stages=storage, admin=admin, sequencer=sequencer)
    dp.include_router(admin_router)   # Telegram-команды /admin тоже работают
    dp.include_router(client_router)

    log.info("Бот запущен. Этапов: %d (включено: %d). Файл: %s",
             len(storage.all()), len(storage.ordered()), cfg.stages_path)
    if not cfg.admin_ids:
        log.warning("ADMIN_ID не задан: первым админом в Telegram станет тот, "
                    "кто пришлёт /admin. Веб-админка защищена паролем.")

    await check_bot_online(bot)
    await poll_forever(bot, dp)


if __name__ == "__main__":
    Config.from_env()  # при ошибке — сразу понятное сообщение
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановка бота")
    except SystemExit:
        raise
    except Exception:
        log.exception("Бот упал с ошибкой")
        print()
        print("!!! BOT CRASHED. Full details: bot_data\\bot.log")
        print()
        raise
