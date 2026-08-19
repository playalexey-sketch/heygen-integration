"""Смоук-тесты без сети: хранилище, отправка этапов, секуэнсер, админ-мастер.

Запуск:  python tests/smoke_test.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ------------------------- фейки Telegram -------------------------


class FakeUser:
    def __init__(self, uid: int):
        self.id = uid


class FakeChat:
    def __init__(self, cid: int, ctype: str = "private"):
        self.id = cid
        self.type = ctype


class FakeBot:
    username = "fakebot"

    def __init__(self, fail_document: bool = False):
        self.sent: list[tuple] = []
        self.fail_document = fail_document

    async def me(self):
        class _Me:
            username = "fakebot"
        return _Me()

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(("message", chat_id, text, kw))
        return "ok"

    async def send_document(self, chat_id, document, caption=None, **kw):
        if self.fail_document:
            raise RuntimeError("document fetch failed")
        self.sent.append(("document", chat_id, document, caption))
        return "ok"

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.sent.append(("photo", chat_id, photo, caption))
        return "ok"

    async def send_video(self, chat_id, video, caption=None, **kw):
        self.sent.append(("video", chat_id, video, caption))
        return "ok"

    async def send_audio(self, chat_id, audio, caption=None, **kw):
        self.sent.append(("audio", chat_id, audio, caption))
        return "ok"


class FakeMessage:
    def __init__(self, bot: FakeBot, text, uid: int = 1, cid: int = 100, ctype="private"):
        self.bot = bot
        self.text = text
        self.from_user = FakeUser(uid)
        self.chat = FakeChat(cid, ctype)
        self.answers: list[tuple] = []
        self.edits: list[tuple] = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))
        return None

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))
        return None


class FakeCallback:
    def __init__(self, bot: FakeBot, data: str, uid: int = 1, cid: int = 100):
        self.bot = bot
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMessage(bot, "stale text", uid=uid, cid=cid)
        self.ack: tuple | None = None

    async def answer(self, text=None, show_alert=False):
        self.ack = (text, show_alert)


class FakeCommand:
    def __init__(self, args=None):
        self.args = args


class FakeState:
    def __init__(self):
        self.state = None
        self.data: dict = {}

    async def set_state(self, s):
        self.state = s

    async def get_state(self):
        return self.state

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kw):
        self.data.update(kw)

    async def clear(self):
        self.state = None
        self.data = {}


# ------------------------- тесты -------------------------


def test_storage(tmp: Path):
    from storage import StageStorage

    p = tmp / "stages.json"
    st = StageStorage(p)
    assert len(st.all()) == 2, "после первого запуска должны появиться 2 стандартных этапа"
    assert st.ordered()[0].content_type == "text"

    s = st.add(10, "link", "https://disk.yandex.ru/abc")
    assert len(st.all()) == 3
    assert s.id == 3

    st.update(s.id, delay_seconds=20, content="https://example.com/a.pdf", enabled=False)
    reloaded = StageStorage(p)  # пересоздали из файла — данные должны сохраниться
    s2 = reloaded.get(s.id)
    assert s2.delay_seconds == 20 and s2.content == "https://example.com/a.pdf" and not s2.enabled
    assert len(reloaded.ordered()) == 2  # выключенный этап не в ordered()

    reloaded.set_enabled(s2.id, True)
    assert reloaded.ordered()[-1].id == s2.id

    first = reloaded.all()[0]
    assert reloaded.move(first.id, -1) is False  # первый некуда выше
    assert reloaded.move(first.id, 1) is True
    assert reloaded.all()[1].id == first.id

    assert reloaded.toggle(s2.id).enabled is False
    assert reloaded.remove(s2.id) is True
    assert reloaded.remove(9999) is False

    # повреждённый файл -> бэкап + стандартные этапы
    p.write_text("{не json", encoding="utf-8")
    st3 = StageStorage(p)
    assert len(st3.all()) == 2
    assert (tmp / "stages.json.broken").exists()
    print("storage: OK")


def test_cross_process_sync(tmp: Path):
    """Бот и админка — разные процессы: админка изменила файл -> бот подхватил после reload."""
    from storage import StageStorage

    p = tmp / "sync.json"
    admin_side = StageStorage(p)   # «процесс админки»
    bot_side = StageStorage(p)     # «процесс бота» (своя копия в памяти)

    assert len(bot_side.all()) == len(admin_side.all())
    before = len(admin_side.all())

    # админка добавляет этап — пишет в файл
    admin_side.add(4, "text", "этап из админки")

    # бот пока не видит (своя копия в памяти)
    assert len(bot_side.all()) == before
    # ...но перечитывает файл перед отправкой — и видит
    bot_side.reload()
    assert len(bot_side.all()) == before + 1
    assert bot_side.all()[-1].content == "этап из админки"

    # порядок: админка удаляет этап — бот подхватывает
    victim = bot_side.all()[-2]
    admin_side.remove(victim.id)
    bot_side.reload()
    assert bot_side.get(victim.id) is None
    print("cross_process_sync: OK")


def test_direct_file_url():
    from sender import is_direct_file_url

    assert is_direct_file_url("https://cdn.example.com/files/report.pdf")
    assert is_direct_file_url("https://x.com/a/b.zip?token=1")
    assert not is_direct_file_url("https://disk.yandex.ru/d/abc123")
    assert not is_direct_file_url("https://drive.google.com/file/d/abc/view")
    assert not is_direct_file_url("ftp://x.com/a.pdf")
    assert not is_direct_file_url("not a url")
    print("is_direct_file_url: OK")


def test_send_stage():
    from sender import send_stage
    from storage import Stage

    async def run():
        bot = FakeBot()
        await send_stage(bot, 100, Stage(1, 0, "text", "Привет, это тест\nвторая строка"))
        assert bot.sent[0][:2] == ("message", 100) and bot.sent[0][2] == "Привет, это тест\nвторая строка"
        assert "parse_mode" not in bot.sent[0][3]

        await send_stage(bot, 100, Stage(2, 0, "link", "https://disk.yandex.ru/d/abc"))
        assert bot.sent[1][0] == "message" and bot.sent[1][2] == "https://disk.yandex.ru/d/abc"

        await send_stage(bot, 100, Stage(3, 0, "link", "https://cdn.example.com/video.mp4"))
        assert bot.sent[2][0] == "document" and bot.sent[2][2] == "https://cdn.example.com/video.mp4"

        await send_stage(bot, 100, Stage(4, 0, "nickname", "@my_nickname"))
        assert bot.sent[3][3].get("parse_mode") == "HTML"
        assert "t.me/my_nickname" in bot.sent[3][2]

        await send_stage(bot, 100, Stage(5, 0, "nickname", "bad nick"))
        assert bot.sent[4][0] == "message"  # деградация в обычный текст

        bot2 = FakeBot(fail_document=True)
        await send_stage(bot2, 100, Stage(6, 0, "link", "https://cdn.example.com/a.pdf"))
        assert bot2.sent[0][0] == "message"  # файл не отдали -> обычная ссылка

        await send_stage(bot, 100, Stage(7, 0, "text", "текст"), prefix="🧪 Тест")
        assert bot.sent[5][2].startswith("🧪 Тест")

    asyncio.run(run())
    print("send_stage: OK")


def test_sequencer(tmp: Path):
    from sender import StageSequencer
    from storage import StageStorage

    async def run():
        st = StageStorage(tmp / "seq.json")
        for _ in st.all():
            st.remove(st.all()[0].id)
        st.add(0, "text", "1-е сообщение")
        st.add(0, "link", "https://example.com/file.pdf")

        bot = FakeBot()
        seq = StageSequencer(st)
        seq.start(bot, 100)
        await asyncio.sleep(0.3)  # даём задаче дойти до конца
        assert not seq.active(100), "задача должна завершиться и сняться с учёта"
        kinds = [k for k, *_ in bot.sent]
        assert kinds == ["message", "document", "message"], f"неожиданный порядок: {kinds}"
        # после последней — кнопка «Получить снова»
        last = bot.sent[-1]
        assert last[3].get("reply_markup") is not None

        # перезапуск /start отменяет старую задачу
        seq.start(bot, 100)
        seq.start(bot, 100)
        assert seq.active(100)
        seq.cancel(100)
        await asyncio.sleep(0.05)
        assert not seq.active(100)

    asyncio.run(run())
    print("sequencer: OK")


def test_media_and_rules(tmp: Path):
    """Медиа-хранилище, правила (exact/contains), отправка медиа-этапа."""
    from content import ContentStorage
    from sender import send_content

    async def run():
        content = ContentStorage(tmp / "mr.json")
        f = tmp / "hello.txt"
        f.write_text("hi", encoding="utf-8")
        m = content.add_media(f, "hello.txt", "document")
        assert m.id == 1 and content.get_media(1) is not None
        assert (content.media_dir / m.filename).exists()
        assert content.get_media("abc") is None

        r1 = content.add_rule("code1", "text", "one")
        r2 = content.add_rule("key", "text", "two", match="contains")
        assert content.find_rule("code1").id == r1.id
        assert content.find_rule("some key here").id == r2.id
        assert content.find_rule("nope") is None
        assert content.toggle_rule(r2.id).enabled is False
        assert content.find_rule("key") is None  # выключенное не срабатывает

        # отправка медиа-контента
        bot = FakeBot()
        ok = await send_content(bot, 100, "media", str(m.id), content)
        assert ok and bot.sent[-1][0] == "document"
        # фото
        png = tmp / "a.png"
        png.write_bytes(b"x")
        mp = content.add_media(png, "a.png", "photo")
        ok = await send_content(bot, 100, "media", str(mp.id), content)
        assert ok and bot.sent[-1][0] == "photo"
        # медиа удалено -> заглушка
        assert content.remove_media(m.id)
        ok = await send_content(bot, 100, "media", "999", content)
        assert not ok

    asyncio.run(run())
    print("media_and_rules: OK")


def test_crm_storage(tmp: Path):
    from crm import CrmStorage

    crm = CrmStorage(tmp / "crm.json")

    class U:
        def __init__(self, id, username="", first_name="", last_name=""):
            self.id = id; self.username = username; self.first_name = first_name; self.last_name = last_name

    r1 = crm.upsert(U(111, "ivan", "Иван", "И."), source="youtube")
    crm.upsert(U(111, "ivan", "Иван", "И."), source="vk")  # повтор: источник обновился
    crm.upsert(U(222, "maria", "Мария", "М."), source="youtube")
    crm.touch(111)

    assert len(crm.all()) == 2
    assert crm.get(111).source == "vk"
    assert crm.get(111).msgs == 1
    assert len(crm.by_source("youtube")) == 1
    assert crm.get(222).first_name == "Мария"

    crm.add_tag(111, "тёплый")
    assert crm.by_tag("тёплый") and crm.by_tag("тёплый")[0].id == 111
    crm.remove_tag(111, "тёплый")
    assert crm.by_tag("тёплый") == []

    assert crm.sources_stats() == {"vk": 1, "youtube": 1}

    # пересоздание из файла
    crm2 = CrmStorage(tmp / "crm.json")
    assert len(crm2.all()) == 2 and crm2.get(222).username == "maria"
    print("crm_storage: OK")


def test_manager(tmp: Path):
    """Менеджер в Telegram: /rules (ссылки), /crm, /mail (рассылка)."""
    from aiogram.exceptions import TelegramForbiddenError

    from content import ContentStorage
    from crm import CrmStorage
    from handlers.manager import cmd_crm, cmd_mail, cmd_rules
    from services import AdminService

    async def run():
        content = ContentStorage(tmp / "mgr_content.json")
        content.add_rule("123", "text", "код-подарок", "exact")
        content.add_rule("vk", "link", "https://vk.com/x", "exact")
        crm = CrmStorage(tmp / "mgr_crm.json")

        class U:
            def __init__(self, id, username=""):
                self.id = id
                self.username = username
                self.first_name = "Ф"
                self.last_name = ""
        crm.upsert(U(111, "ivan"), source="youtube")
        crm.upsert(U(222, "maria"), source="vk")
        crm.add_tag(111, "тёплый")

        admin = AdminService(frozenset({1}))
        bot = FakeBot()

        # /rules: список + ссылки
        msg = FakeMessage(bot, "/rules", uid=1, cid=10)
        await cmd_rules(msg, admin, content)
        text = msg.answers[0][0]
        assert "https://t.me/fakebot?start=123" in text
        assert "https://t.me/fakebot?start=vk" in text
        assert "youtube" in text and "instagram" in text  # соц-ссылки

        # /crm: статистика
        msg = FakeMessage(bot, "/crm", uid=1, cid=10)
        await cmd_crm(msg, admin, crm)
        text = msg.answers[0][0]
        assert "клиентов 2" in text
        assert "youtube" in text and "тёплый" in text

        # /mail all: рассылка + отчёт
        msg = FakeMessage(bot, "/mail all Привет всем!", uid=1, cid=10)
        await cmd_mail(msg, admin, crm)
        assert any("Рассылка запущена" in a[0] for a in msg.answers)
        await asyncio.sleep(1.0)
        got = [s[2] for s in bot.sent if s[0] == "message"]
        assert got.count("Привет всем!") == 2, f"рассылка не всем: {got}"
        assert any("доставлено 2" in t for t in got), "нет отчёта о доставке"

        # /mail tag: выборочная
        bot.sent.clear()
        msg = FakeMessage(bot, "/mail tag:тёплый Для тёплых", uid=1, cid=10)
        await cmd_mail(msg, admin, crm)
        await asyncio.sleep(0.8)
        got = [s[2] for s in bot.sent if s[0] == "message"]
        assert got.count("Для тёплых") == 1

        # заблокировавший бота клиент: отметка blocked
        bot.sent.clear()

        class BlockingBot(FakeBot):
            async def send_message(self, chat_id, text, **kw):
                if chat_id == 222:
                    raise TelegramForbiddenError(method=None, message="blocked")
                await super().send_message(chat_id, text, **kw)
        b2 = BlockingBot()
        msg = FakeMessage(b2, "/mail all Второй раунд", uid=1, cid=10)
        await cmd_mail(msg, admin, crm)
        await asyncio.sleep(0.8)
        assert crm.get(222).blocked is True, "заблокировавший не отмечен"
        assert any("сбоев 1" in s[2] for s in b2.sent if s[0] == "message")

    asyncio.run(run())
    print("manager: OK")


def test_admin_service():
    from services import AdminService

    a = AdminService(frozenset({42}))
    assert a.is_admin(42) and not a.is_admin(7) and not a.allow_anyone()

    b = AdminService(frozenset())
    assert b.allow_anyone() and not b.is_admin(7)
    b.promote(7)
    assert b.is_admin(7) and not b.allow_anyone()
    print("admin_service: OK")


def test_config():
    os.environ["BOT_TOKEN"] = ""
    from config import Config

    try:
        Config.from_env()
        raise AssertionError("должен был завершиться с ошибкой без токена")
    except SystemExit:
        pass

    os.environ["BOT_TOKEN"] = "123:ABC"
    os.environ["ADMIN_ID"] = "1, 2;3"
    cfg = Config.from_env()
    assert cfg.admin_ids == frozenset({1, 2, 3})
    print("config: OK")


def test_client_flow(tmp: Path):
    """Клиент: /start -> все этапы по порядку -> кнопка «Получить снова»."""
    from handlers.client import cb_restart, cmd_start
    from sender import StageSequencer
    from services import AdminService
    from storage import StageStorage

    async def run():
        st = StageStorage(tmp / "client.json")
        for _ in st.all():
            st.remove(st.all()[0].id)
        st.add(0, "text", "Привет! 👋")
        st.add(0, "link", "https://disk.yandex.ru/d/xyz")
        st.add(0, "nickname", "@support_nik")

        from content import ContentStorage
        from crm import CrmStorage
        content = ContentStorage(tmp / "client_content.json")
        content.add_rule("123", "text", "Бонус по коду 123!")
        crm = CrmStorage(tmp / "client_crm.json")

        admin = AdminService(frozenset({999}))
        seq = StageSequencer(st, content)
        bot = FakeBot()
        state = FakeState()

        msg = FakeMessage(bot, "/start", uid=555, cid=200)
        await cmd_start(msg, FakeCommand(None), seq, admin, content, crm)
        assert any("Готово" in a[0] for a in msg.answers)

        await asyncio.sleep(0.3)
        texts = [x[2] for x in bot.sent]
        assert "Привет! 👋" in texts
        assert "https://disk.yandex.ru/d/xyz" in texts
        assert any("support_nik" in t for t in texts)
        assert not any("Бонус по коду" in t for t in texts), "без кода правило не должно сработать"

        # deep-link: /start с кодом 123 -> правило срабатывает
        msg_code = FakeMessage(bot, "/start 123", uid=555, cid=200)
        await cmd_start(msg_code, FakeCommand("123"), seq, admin, content, crm)
        await asyncio.sleep(0.4)
        texts = [x[2] for x in bot.sent]
        assert any("Бонус по коду 123!" in t for t in texts), "правило по коду из deep-link не сработало"

        # клиент ввёл ключевое слово текстом -> сработало
        msg_kw = FakeMessage(bot, "123", uid=555, cid=200)
        from handlers.client import client_text
        await client_text(msg_kw, admin, content, crm)
        assert any("Бонус по коду 123!" in x[2] for x in bot.sent), "правило по введённому тексту не сработало"
        assert not msg_kw.answers, "при сработавшем правиле подсказка не нужна"

        # клиент ввёл что-то другое -> подсказка
        msg_other = FakeMessage(bot, "привет", uid=555, cid=200)
        await client_text(msg_other, admin, content, crm)
        assert any("/start" in a[0] for a in msg_other.answers), "подсказка не пришла"

        # CRM: клиент записан, источник — код из deep-link
        rec = crm.get(555)
        assert rec is not None, "клиент не записан в CRM"
        assert rec.source == "123", f"источник должен быть 123, а не {rec.source!r}"
        assert rec.msgs >= 1, "сообщения клиента не учтены"

        # админ /start -> не клиент
        msg_admin = FakeMessage(bot, "/start", uid=999, cid=300)
        before = len(bot.sent)
        await cmd_start(msg_admin, FakeCommand(None), seq, admin, content, crm)
        assert len(bot.sent) == before
        assert any("администратор" in a[0].lower() for a in msg_admin.answers)

        # кнопка «Получить снова» перезапускает
        n_before = len(bot.sent)
        cb = FakeCallback(bot, "client:restart", uid=555, cid=200)
        await cb_restart(cb, seq, admin, crm)
        assert cb.ack is not None
        await asyncio.sleep(0.3)
        assert len(bot.sent) > n_before, "после restart должны прийти сообщения"

    asyncio.run(run())
    print("client_flow: OK")


def test_admin_flow(tmp: Path):
    """Админ: /admin -> мастер (задержка, тип, контент) -> список -> кнопки."""
    from handlers.admin import (
        cb_del,
        cb_move,
        cb_stages,
        cb_toggle,
        cb_wizard_edit,
        cmd_admin,
        cmd_add,
        cmd_del,
        cmd_edit,
        cmd_stages,
        wizard_content,
        wizard_delay,
        wizard_type,
    )
    from services import AdminService
    from storage import StageStorage

    async def run():
        st = StageStorage(tmp / "admin.json")
        from content import ContentStorage
        content = ContentStorage(tmp / "admin_content.json")
        bot = FakeBot()
        state = FakeState()

        # первый пользователь в режиме «открыт» становится админом
        admin = AdminService(frozenset())
        m = FakeMessage(bot, "/admin", uid=111, cid=10)
        await cmd_admin(m, admin)
        assert admin.is_admin(111), "первый пользователь должен стать админом"
        assert any("администратором" in a[0].lower() for a in m.answers)

        # чужому — отказ
        stranger = FakeMessage(bot, "/admin", uid=222, cid=11)
        await cmd_admin(stranger, admin)
        assert any("Доступ запрещён" in a[0] for a in stranger.answers)

        # мастер: новый этап
        m = FakeMessage(bot, "/add", uid=111, cid=10)
        await cmd_add(m, state, admin)
        assert state.state is not None
        assert any("Шаг 1/3" in a[0] for a in m.answers)

        m2 = FakeMessage(bot, "abc", uid=111, cid=10)
        await wizard_delay(m2, state)  # не число -> повторный запрос
        assert state.state is not None and any("неотрицательное целое число" in a[0] for a in m2.answers)

        m3 = FakeMessage(bot, "15", uid=111, cid=10)
        await wizard_delay(m3, state)
        assert any("Шаг 2/3" in a[0] for a in m3.answers)

        cb = FakeCallback(bot, "type:link", uid=111, cid=10)
        await wizard_type(cb, state)
        assert any("ссылку" in a[0].lower() for a in cb.message.answers)

        m4 = FakeMessage(bot, "https://disk.yandex.ru/d/abc123", uid=111, cid=10)
        await wizard_content(m4, state, st, content)
        stages = st.all()
        assert stages[-1].content_type == "link"
        assert stages[-1].delay_seconds == 15
        assert stages[-1].content == "https://disk.yandex.ru/d/abc123"
        assert state.state is None

        # некорректная ссылка отклоняется
        m_bad = FakeMessage(bot, "https://disk.yandex.ru/d/abc123", uid=111, cid=10)
        m_bad.text = "не ссылка"
        await cmd_add(m_bad, state, admin)
        await wizard_delay(FakeMessage(bot, "0", uid=111, cid=10), state)
        await wizard_type(FakeCallback(bot, "type:link", uid=111, cid=10), state)
        before = len(st.all())
        await wizard_content(m_bad, state, st, content)
        assert len(st.all()) == before, "некорректную ссылку нельзя сохранить"

        # список этапов (команда и кнопка)
        m5 = FakeMessage(bot, "/stages", uid=111, cid=10)
        await cmd_stages(m5, state, admin, st, content)
        assert any("📋 Этапы" in a[0] for a in m5.answers)

        cb2 = FakeCallback(bot, "menu:stages", uid=111, cid=10)
        await cb_stages(cb2, admin, st, content)
        assert cb2.message.edits or cb2.message.answers

        # редактирование через кнопку: изменить задержку
        target = st.all()[-1]
        cb3 = FakeCallback(bot, f"wizard:edit:{target.id}", uid=111, cid=10)
        await cb_wizard_edit(cb3, state, admin, st)
        assert state.data.get("mode") == "edit" and state.data.get("stage_id") == target.id
        await wizard_delay(FakeMessage(bot, "30", uid=111, cid=10), state)
        await wizard_type(FakeCallback(bot, "type:text", uid=111, cid=10), state)
        await wizard_content(FakeMessage(bot, "Новый текст", uid=111, cid=10), state, st, content)
        assert st.get(target.id).delay_seconds == 30
        assert st.get(target.id).content == "Новый текст"
        assert st.get(target.id).content_type == "text"

        # удаление (команда и кнопка)
        last = st.all()[-1]
        m6 = FakeMessage(bot, f"/del {len(st.all())}", uid=111, cid=10)
        await cmd_del(m6, admin, st)
        assert st.get(last.id) is None, "этап должен быть удалён командой /del"

        remaining = st.all()
        cb4 = FakeCallback(bot, f"del:{remaining[0].id}", uid=111, cid=10)
        await cb_del(cb4, admin, st, content)
        assert st.get(remaining[0].id) is None

        # движение и переключение (добавляем этап, чтобы было минимум два)
        while len(st.all()) < 2:
            st.add(0, "text", "дополнительный этап")
        a1, a2 = st.all()[0], st.all()[1]
        cb5 = FakeCallback(bot, f"move:{a1.id}:1", uid=111, cid=10)
        await cb_move(cb5, admin, st, content)
        ids = [s.id for s in st.all()]
        assert ids.index(a2.id) < ids.index(a1.id)

        cb6 = FakeCallback(bot, f"toggle:{a1.id}", uid=111, cid=10)
        await cb_toggle(cb6, admin, st, content)
        assert st.get(a1.id).enabled is False

        # /edit с неверным номером
        m7 = FakeMessage(bot, "/edit 99", uid=111, cid=10)
        await cmd_edit(m7, state, admin, st)
        assert any("номер этапа" in a[0].lower() for a in m7.answers)

    asyncio.run(run())
    print("admin_flow: OK")


def test_router_wiring():
    """Роутеры собираются, фильтр IsAdmin работает, dp создаётся."""
    import asyncio

    from aiogram import Dispatcher

    from handlers.admin import IsAdmin, router as admin_router
    from handlers.client import router as client_router
    from services import AdminService

    admin = AdminService(frozenset({42}))
    msg_admin = FakeMessage(FakeBot(), "x", uid=42)
    msg_other = FakeMessage(FakeBot(), "x", uid=43)
    assert asyncio.run(IsAdmin()(msg_admin, admin=admin)) is True
    assert asyncio.run(IsAdmin()(msg_other, admin=admin)) is False
    assert asyncio.run((~IsAdmin())(msg_other, admin=admin)) is True
    assert asyncio.run((~IsAdmin())(msg_admin, admin=admin)) is False

    dp = Dispatcher(storage=None, content=None, admin=None, sequencer=None)
    dp.include_router(admin_router)
    dp.include_router(client_router)
    print("router_wiring: OK")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_storage(tmp / "s1")
        test_cross_process_sync(tmp / "s5")
        test_media_and_rules(tmp / "s6")
        test_crm_storage(tmp / "s7")
        test_manager(tmp / "s8")
        test_direct_file_url()
        test_send_stage()
        test_sequencer(tmp / "s2")
        test_admin_service()
        test_config()
        test_client_flow(tmp / "s3")
        test_admin_flow(tmp / "s4")
        test_router_wiring()
    print("\nВсе тесты прошли ✅")


if __name__ == "__main__":
    main()
