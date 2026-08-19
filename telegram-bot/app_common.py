"""Общее для двух процессов (bot.py и admin.py): конфиг, логи, прокси, сборка объектов."""
from __future__ import annotations

import logging
import socket
import ssl

import certifi
from aiohttp import TCPConnector
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramUnauthorizedError

from config import Config
from content import ContentStorage
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


def load_proxy(cfg: Config) -> str:
    """Актуальный прокси: bot_data/proxy.txt (меняется из веб-панели) -> .env."""
    try:
        if cfg.proxy_path.exists():
            return cfg.proxy_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return cfg.telegram_proxy


def apply_proxy(bot: Bot, proxy: str) -> None:
    """Применить прокси (или отключить его) к живой сессии бота."""
    session = getattr(bot, "session", None)
    if not isinstance(session, AiohttpSession):
        return
    try:
        if proxy:
            session.proxy = proxy  # aiogram сам пересоздаёт коннектор
            log.info("Прокси для Telegram включён: %s", proxy)
        elif session.proxy is not None:
            # Возврат к прямому соединению (IPv4): восстанавливаем дефолтный коннектор.
            session._connector_type = TCPConnector  # noqa: SLF001
            session._connector_init = {  # noqa: SLF001
                "ssl": ssl.create_default_context(cafile=certifi.where()),
                "limit": 100,
                "ttl_dns_cache": 3600,
                "family": socket.AF_INET,
            }
            session._proxy = None  # noqa: SLF001
            session._should_reset_connector = True  # noqa: SLF001
            log.info("Прокси для Telegram отключён — прямое соединение")
    except Exception:
        log.exception("Не удалось применить прокси %r", proxy)


def setup(
    cfg: Config, log_name: str = "bot.log"
) -> tuple[StageStorage, AdminService, StageSequencer, Bot, ContentStorage]:
    """Логирование в файл + сборка общих объектов.

    :param log_name: имя лог-файла в DATA_DIR (у бота — bot.log, у админки — admin.log)
    """
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(cfg.data_dir / log_name, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)

    storage = StageStorage(cfg.stages_path)
    content = ContentStorage(cfg.data_dir / "content.json")
    admin = AdminService(cfg.admin_ids)
    sequencer = StageSequencer(storage, content)

    proxy = load_proxy(cfg)
    if proxy:
        try:
            session = AiohttpSession(proxy=proxy)
        except ImportError:
            log.error("Для socks5-прокси нужен пакет aiohttp-socks: pip install aiohttp-socks")
            session = IPv4AiohttpSession()
        log.info("Подключение к Telegram через прокси: %s", proxy)
    else:
        session = IPv4AiohttpSession()
    bot = Bot(token=cfg.bot_token, session=session)
    return storage, admin, sequencer, bot, content


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
