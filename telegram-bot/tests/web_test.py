"""Тесты веб-панели (read-only): логин, статус, этапы, медиа, правила, CRM.

Запуск:  python tests/web_test.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from config import Config
from sender import StageSequencer
from services import AdminService
from storage import StageStorage
from web_panel import create_app


class FakeBot:
    def __init__(self):
        self.sent: list[tuple] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(("message", chat_id, text, kw))
        return None

    async def send_document(self, chat_id, document, **kw):
        self.sent.append(("document", chat_id, document, kw))
        return None

    async def send_photo(self, chat_id, photo, **kw):
        self.sent.append(("photo", chat_id, photo, kw))
        return None

    async def me(self):
        class _Me:
            username = "testbot"
        return _Me()


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg = Config(
            bot_token="123:TEST",
            web_password="testpass",
            data_dir=tmp / "data",
        )
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        storage = StageStorage(tmp / "stages.json")
        from content import ContentStorage
        from convo import ConvoStorage, DIR_IN
        from crm import CrmStorage
        content = ContentStorage(tmp / "data" / "content.json")
        crm = CrmStorage(tmp / "data" / "crm.json")
        convo = ConvoStorage(tmp / "data" / "chats.json")
        bot = FakeBot()
        admin = AdminService(frozenset({1}))
        sequencer = StageSequencer(storage, content)
        app = create_app(cfg, storage, content, crm, convo, bot, sequencer, admin, started_at=time.time())

        # данные, которые "сделал бот" в своём процессе:
        storage.add(5, "text", "Привет из бота")
        content.add_rule("123", "text", "по коду", "exact")
        content.add_rule("vk", "link", "https://vk.com/abc", "exact")

        with TestClient(app) as client:
            # --- страница и health ---
            r = client.get("/")
            assert r.status_code == 200 and "CRM" in r.text
            assert client.get("/api/health").json() == {"ok": True}
            print("страница + health: OK")

            # --- без логина 401 ---
            assert client.get("/api/stages").status_code == 401
            assert client.get("/api/crm").status_code == 401
            print("без логина 401: OK")

            # --- логин ---
            assert client.post("/api/login", json={"password": "bad"}).status_code == 401
            assert client.post("/api/login", json={"password": "testpass"}).status_code == 200
            print("логин: OK")

            # --- статус ---
            st = client.get("/api/status").json()
            assert st["bot"] == "@testbot" and "crm_total" in st and "rules_total" in st
            print("статус: OK")

            # --- этапы (read-only) ---
            stages = client.get("/api/stages").json()["stages"]
            assert len(stages) == 3 and stages[-1]["content"] == "Привет из бота"
            # мутаций нет:
            assert client.post("/api/stages", json={"delay_seconds": 0, "content_type": "text", "content": "x"}).status_code == 405
            print("этапы read-only: OK")

            # --- медиа (read-only) ---
            media = client.get("/api/media").json()
            assert media["media"] == []
            assert client.post("/api/media", files={"file": ("a.txt", b"x")}).status_code == 405
            print("медиа read-only: OK")

            # --- правила (read-only, со ссылками) ---
            rules = client.get("/api/rules").json()
            assert len(rules["rules"]) == 2
            assert rules["rules"][0]["link"].endswith("?start=123")
            assert client.post("/api/rules", json={"trigger": "x", "content_type": "text", "content": "y"}).status_code == 405
            print("правила read-only + ссылки: OK")

            # --- CRM ---
            class U:
                id = 555
                username = "ivan"
                first_name = "Иван"
                last_name = ""
            crm.upsert(U(), source="youtube")
            crm.touch(555)
            d = client.get("/api/crm").json()
            assert d["total"] == 1
            assert d["sources"]["youtube"] == 1
            assert d["clients"][0]["username"] == "ivan"
            assert d["clients"][0]["source"] == "youtube"
            assert d["clients"][0]["msgs"] == 1
            print("CRM: OK")

            # --- прокси (read-only) ---
            p = client.get("/api/proxy").json()
            assert "proxy" in p
            assert client.post("/api/proxy", json={"proxy": "socks5://127.0.0.1:1"}).status_code == 405
            print("прокси read-only: OK")

            # --- чаты/переписка ---
            class U2:
                id = 555
                username = "ivan"
                first_name = "Иван"
                last_name = ""
            crm.upsert(U2(), source="youtube")
            convo.add_message(555, "привет бот", DIR_IN)
            ch = client.get("/api/chats").json()
            assert ch["chats"] and ch["chats"][0]["chat_id"] == 555
            assert ch["chats"][0]["client"]["username"] == "ivan"
            one = client.get("/api/chat/555").json()
            assert one["messages"] and one["messages"][0]["text"] == "привет бот"
            r = client.post("/api/send", json={"chat_id": 555, "text": "ответ админа"})
            assert r.json() == {"ok": True}
            assert any(s2[0] == "message" and s2[1] == 555 and s2[2] == "ответ админа" for s2 in bot.sent)
            msgs = client.get("/api/chat/555").json()["messages"]
            assert msgs[-1]["direction"] == "out"
            assert client.post("/api/send", json={"chat_id": 999, "text": "x"}).status_code == 404
            print("чаты/переписка: OK")

            # --- logout ---
            assert client.post("/api/logout").status_code == 200
            assert client.get("/api/stages").status_code == 401
            print("logout: OK")

    print("\nТесты веб-панели прошли ✅")


if __name__ == "__main__":
    run()
