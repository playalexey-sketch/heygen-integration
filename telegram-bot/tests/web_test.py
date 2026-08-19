"""Тесты веб-панели: логин, CRUD этапов, порядок, вкл/выкл, тест-отправка.

Запуск:  python tests/web_test.py
Нужен httpx (в dev):  pip install httpx
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
        storage = StageStorage(tmp / "stages.json")
        bot = FakeBot()
        admin = AdminService(frozenset({1}))
        sequencer = StageSequencer(storage)
        app = create_app(cfg, storage, bot, sequencer, admin, started_at=time.time())

        with TestClient(app) as client:
            # --- страница и health ---
            r = client.get("/")
            assert r.status_code == 200 and "Панель" in r.text
            assert client.get("/api/health").json() == {"ok": True}
            print("страница + health: OK")

            # --- без логина доступ закрыт ---
            assert client.get("/api/stages").status_code == 401
            print("без логина 401: OK")

            # --- логин ---
            assert client.post("/api/login", json={"password": "bad"}).status_code == 401
            r = client.post("/api/login", json={"password": "testpass"})
            assert r.status_code == 200
            print("логин: OK")

            # --- статус ---
            st = client.get("/api/status").json()
            assert st["bot"] == "@testbot" and "stages_total" in st
            print("статус: OK")

            # --- список (стартовое демо: 2 этапа) ---
            stages = client.get("/api/stages").json()["stages"]
            assert len(stages) == 2 and stages[0]["position"] == 1

            # --- валидация ---
            r = client.post("/api/stages", json={"delay_seconds": "abc", "content_type": "text", "content": "x"})
            assert r.status_code == 400
            r = client.post("/api/stages", json={"delay_seconds": 0, "content_type": "link", "content": "не ссылка"})
            assert r.status_code == 400
            r = client.post("/api/stages", json={"delay_seconds": 0, "content_type": "nickname", "content": "ab"})
            assert r.status_code == 400
            print("валидация: OK")

            # --- добавление ---
            r = client.post(
                "/api/stages",
                json={"delay_seconds": 5, "content_type": "link", "content": "https://disk.yandex.ru/d/xyz"},
            )
            assert r.status_code == 200 and r.json()["content_type"] == "link"
            new_id = r.json()["id"]

            r = client.post(
                "/api/stages",
                json={"delay_seconds": 10, "content_type": "nickname", "content": "@support_team"},
            )
            assert r.status_code == 200 and r.json()["content"] == "@support_team"
            nick_id = r.json()["id"]

            # --- редактирование ---
            r = client.patch(
                f"/api/stages/{new_id}",
                json={"delay_seconds": 7, "content_type": "text", "content": "Привет из веба"},
            )
            assert r.status_code == 200 and r.json()["content"] == "Привет из веба"
            got = client.get("/api/stages").json()["stages"]
            assert [s for s in got if s["id"] == new_id][0]["delay_seconds"] == 7

            # --- порядок ---
            first = client.get("/api/stages").json()["stages"][0]
            r = client.post(f"/api/stages/{first['id']}/move", json={"direction": 1})
            assert r.status_code == 200
            after = client.get("/api/stages").json()["stages"]
            assert after[1]["id"] == first["id"]
            # в конце — нельзя опустить
            last = after[-1]
            r = client.post(f"/api/stages/{last['id']}/move", json={"direction": 1})
            assert r.status_code == 400
            print("CRUD + порядок: OK")

            # --- вкл/выкл ---
            r = client.post(f"/api/stages/{nick_id}/toggle")
            assert r.status_code == 200 and r.json()["enabled"] is False
            assert len([s for s in client.get("/api/stages").json()["stages"] if s["enabled"]]) == len(client.get("/api/stages").json()["stages"]) - 1
            client.post(f"/api/stages/{nick_id}/toggle")
            print("вкл/выкл: OK")

            # --- тест-отправка в чат ---
            r = client.post("/api/test", json={"chat_id": "не число"})
            assert r.status_code == 400
            r = client.post("/api/test", json={"chat_id": 777, "live": False})
            assert r.status_code == 200
            time.sleep(0.5)  # фоновая задача отправки
            assert any(k == "message" and cid == 777 for k, cid, *_ in bot.sent), bot.sent
            assert any("Тест" in t for _, _, t, _ in bot.sent), "тестовые сообщения не отправлены"
            print("тест-отправка: OK")

            # --- удаление ---
            r = client.delete(f"/api/stages/{nick_id}")
            assert r.status_code == 200
            assert client.delete(f"/api/stages/{nick_id}").status_code == 404
            assert client.get("/api/stages").json()["stages"] and all(
                s["id"] != nick_id for s in client.get("/api/stages").json()["stages"]
            )
            print("удаление: OK")

            # --- прокси: чтение/сохранение ---
            p = client.get("/api/proxy").json()
            assert p["proxy"] == "" and p["file_exists"] is False
            r = client.post("/api/proxy", json={"proxy": "socks5://127.0.0.1:1"}).json()
            # локально соединения нет: ok=False, но прокси сохранён
            assert r["ok"] is False
            assert client.get("/api/proxy").json()["proxy"] == "socks5://127.0.0.1:1"
            # очистка
            client.post("/api/proxy", json={"proxy": ""})
            assert client.get("/api/proxy").json()["proxy"] == ""
            print("прокси: OK")

            # --- check_telegram с явно указанным прокси (локально — ошибка) ---
            r = client.post("/api/check_telegram", json={"proxy": "socks5://127.0.0.1:1"}).json()
            assert r["ok"] is False and r["error"]
            print("check_telegram: OK")

            # --- logout ---
            assert client.post("/api/logout").status_code == 200
            assert client.get("/api/stages").status_code == 401
            print("logout: OK")

    print("\nТесты веб-панели прошли ✅")


if __name__ == "__main__":
    run()
