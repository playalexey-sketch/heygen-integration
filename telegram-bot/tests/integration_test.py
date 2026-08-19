"""Интеграционный тест: полное прохождение событий через настоящий Dispatcher
aiogram (роутеры, фильтры, FSM, workflow data) с офлайн-ботом.

Запуск:  python tests/integration_test.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from handlers.admin import router as admin_router
from handlers.client import router as client_router
from sender import StageSequencer
from services import AdminService
from storage import StageStorage


class OfflineBot(Bot):
    """Bot без сети: перехватывает Telegram-методы на уровне Bot.__call__."""

    def __init__(self):
        super().__init__(token="123456789:TESTTOKEN")
        self.sent: list[tuple] = []

    def _mk_msg(self, chat_id: int, text: str | None = None) -> Message:
        return Message(
            message_id=len(self.sent) + 1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            text=text,
        )

    async def __call__(self, method, *, request_timeout=None):
        name = type(method).__name__
        if name == "SendMessage":
            self.sent.append(
                ("message", method.chat_id, method.text, {"reply_markup": method.reply_markup})
            )
            return self._mk_msg(method.chat_id, method.text)
        if name == "SendDocument":
            self.sent.append(("document", method.chat_id, method.document, {"caption": method.caption}))
            return self._mk_msg(method.chat_id)
        if name == "AnswerCallbackQuery":
            self.sent.append(("cb_answer", method.callback_query_id, {}))
            return True
        if name == "EditMessageText":
            target = getattr(method, "chat_id", None) or getattr(method, "message_id", None)
            self.sent.append(("edit", target, method.text, {}))
            return True
        raise RuntimeError(f"Непредвиденный метод Telegram API: {name}")


def mk_user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"user{uid}")


def mk_message(uid: int, chat_id: int, text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id, type="private"),
        from_user=mk_user(uid),
        text=text,
    )


def upd_message(uid: int, chat_id: int, text: str) -> Update:
    return Update(update_id=1, message=mk_message(uid, chat_id, text))


def upd_callback(uid: int, chat_id: int, data: str) -> Update:
    cb = CallbackQuery(
        id="cb1",
        from_user=mk_user(uid),
        chat_instance="1",
        data=data,
        message=mk_message(uid, chat_id, "старое сообщение с меню"),
    )
    return Update(update_id=2, callback_query=cb)


def texts(bot: OfflineBot, chat_id: int) -> list[str]:
    return [s[2] for s in bot.sent if s[0] == "message" and s[1] == chat_id]


async def run() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        storage = StageStorage(Path(tmp) / "stages.json")
        # чистый сценарий: привет -> ссылка -> ник
        for stage in list(storage.all()):
            storage.remove(stage.id)
        storage.add(0, "text", "Привет от бота!")
        storage.add(0, "link", "https://disk.yandex.ru/d/abc123")
        storage.add(0, "nickname", "@my_support_nik")

        admin = AdminService(frozenset())  # режим «открыт» — первый /admin станет админом
        sequencer = StageSequencer(storage)
        bot = OfflineBot()

        dp = Dispatcher(stages=storage, admin=admin, sequencer=sequencer)
        dp.include_router(admin_router)
        dp.include_router(client_router)

        # ---------- 1. клиент: /start -> последовательность ----------
        await dp.feed_update(bot, upd_message(555, 200, "/start"))
        await asyncio.sleep(0.3)  # даём фоновой задаче дослать этапы

        client_msgs = texts(bot, 200)
        assert "Привет от бота!" in client_msgs, client_msgs
        assert "https://disk.yandex.ru/d/abc123" in client_msgs, client_msgs
        assert any("my_support_nik" in t for t in client_msgs), client_msgs
        last = [s for s in bot.sent if s[0] == "message" and s[1] == 200][-1]
        kb = last[3]["reply_markup"]
        assert kb is not None, "после сценария должна быть кнопка «Получить снова»"
        assert [b.callback_data for row in kb.inline_keyboard for b in row] == ["client:restart"]
        print("1. клиент /start -> 3 этапа + кнопка: OK")

        # ---------- 2. клиент: обычный текст -> подсказка ----------
        await dp.feed_update(bot, upd_message(555, 200, "привет, а что делать?"))
        assert any("/start" in t for t in texts(bot, 200)[-1:]), "подсказка клиенту не пришла"
        print("2. клиенту пришёл подсказка /start: OK")

        # ---------- 3. первый /admin -> стал админом ----------
        await dp.feed_update(bot, upd_message(111, 100, "/admin"))
        assert admin.is_admin(111), "первый пользователь должен стать админом"
        assert any("администратором" in t.lower() for t in texts(bot, 100))
        print("3. первый /admin стал админом: OK")

        # ---------- 4. чужому /stages -> отказ ----------
        await dp.feed_update(bot, upd_message(555, 200, "/stages"))
        assert any("Доступ запрещён" in t for t in texts(bot, 200)), "чужой должен получить отказ"
        print("4. чужому /stages — отказ: OK")

        # ---------- 5. админ: мастер /add ----------
        await dp.feed_update(bot, upd_message(111, 100, "/add"))
        await dp.feed_update(bot, upd_message(111, 100, "12"))
        await dp.feed_update(bot, upd_callback(111, 100, "type:text"))
        await dp.feed_update(bot, upd_message(111, 100, "Четвёртый этап текста"))
        assert storage.all()[-1].content == "Четвёртый этап текста"
        assert storage.all()[-1].delay_seconds == 12
        assert any("Этап добавлен" in t for t in texts(bot, 100))
        print("5. мастер /add создал этап: OK")

        # ---------- 6. админ: /stages -> список, кнопка «включить/выключить» ----------
        await dp.feed_update(bot, upd_message(111, 100, "/stages"))
        assert any("📋 Этапы" in t for t in texts(bot, 100))
        target = storage.all()[-1]
        await dp.feed_update(bot, upd_callback(111, 100, f"toggle:{target.id}"))
        assert storage.get(target.id).enabled is False
        print("6. /stages + переключение этапа кнопкой: OK")

        # ---------- 7. админ: /del ----------
        await dp.feed_update(bot, upd_message(111, 100, f"/del {len(storage.all())}"))
        assert storage.get(target.id) is None
        print("7. /del удалил этап: OK")

        # ---------- 8. админ: /test (сразу) ----------
        await dp.feed_update(bot, upd_message(111, 100, "/test"))
        await asyncio.sleep(0.3)
        assert any("🧪 Тест, этап 1/3" in t for t in texts(bot, 100)), "тестовые подписи не пришли"
        assert any("Тест завершён" in t for t in texts(bot, 100))
        print("8. /test прогнал сценарий: OK")

        # ---------- 9. клиент: кнопка «Получить снова» ----------
        n = len(bot.sent)
        await dp.feed_update(bot, upd_callback(555, 200, "client:restart"))
        await asyncio.sleep(0.3)
        assert len(bot.sent) > n, "после restart ничего не пришло"
        print("9. «Получить снова» перезапустило отработку: OK")

        # ---------- 10. админ вне мастера: текст -> подсказка про /admin ----------
        await dp.feed_update(bot, upd_message(111, 100, "просто текст"))
        assert any("/admin" in t for t in texts(bot, 100)[-1:])
        print("10. админу подсказка про /admin: OK")

    print("\nИнтеграционный тест пройден ✅")


if __name__ == "__main__":
    asyncio.run(run())
