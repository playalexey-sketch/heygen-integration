"""Общее для двух процессов (bot.py и admin.py): конфиг, логи, сборка объектов."""
from __future__ import annotations

import logging
import socket

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramUnauthorizedError

from config import Config
from sender import StageSequencer
from services import AdminService
from storage import StageStorage

log = logging.getLogger("common")


class IPv4AiohttpSession(AiohttpSession):
    """Сессия с принудительным IPv4.

    На части Windows-машин IPv6 к api.telegram.org «зависает» и даёт ошибку
    ClientConnectorError [Превышен таймаут семафора]. IPv4 это обходит.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init.setdefault("family", socket.AF_INET)


def setup(cfg: Config, log_name: str = "bot.log") -> tuple[StageStorage, AdminService, StageSequencer, Bot]:
    """Логирование в файл + сборка общих объектов.

    :param log_name: имя лог-файла в DATA_DIR (у бота — bot.log, у админки — admin.log)
    """
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(cfg.data_dir / log_name, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)

    storage = StageStorage(cfg.stages_path)
    admin = AdminService(cfg.admin_ids)
    sequencer = StageSequencer(storage)
    bot = Bot(token=cfg.bot_token, session=IPv4AiohttpSession())
    return storage, admin, sequencer, bot


async def check_bot_online(bot: Bot) -> None:
    """Однократно проверить соединение с Telegram (информационно, не критично)."""
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
            "Продолжаю — запросы будут повторяться."
        )
