"""Переписка: все сообщения клиентов и ответы админа (от имени бота).

Файл bot_data/chats.json общий для обоих процессов:
- процесс бота пишет входящие (клиент -> бот) и исходящие (ответ админа из Telegram);
- веб-админка пишет исходящие (ответ админа из веб-формы) и читает переписку.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("convo")

DIR_IN = "in"    # клиент -> бот
DIR_OUT = "out"  # админ (от имени бота) -> клиент

MAX_MESSAGES = 20000  # глобальный потолок, старые отбрасываются


@dataclass
class ConvoMsg:
    id: int
    chat_id: int      # ID клиента
    text: str         # текст (для медиа — подпись вида "[фото]")
    direction: str    # in / out
    ts: str           # "YYYY-MM-DD HH:MM"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "chat_id": self.chat_id, "text": self.text,
            "direction": self.direction, "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConvoMsg":
        return cls(
            id=int(d["id"]), chat_id=int(d["chat_id"]), text=str(d.get("text", "")),
            direction=d.get("direction", DIR_IN), ts=str(d.get("ts", "")),
        )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def media_label(msg_type: str) -> str:
    return {
        "photo": "[фото]", "video": "[видео]", "animation": "[GIF/видео]",
        "audio": "[аудио]", "document": "[файл]", "voice": "[голосовое]",
    }.get(msg_type, "[медиа]")


class ConvoStorage:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.messages: list[ConvoMsg] = []
        self._next_id = 1
        self._load()

    # ---------- загрузка / сохранение ----------

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.messages = [ConvoMsg.from_dict(m) for m in data.get("messages", [])]
                self._next_id = int(data.get("next_id", 1))
                if self.messages:
                    self._next_id = max(self._next_id, max(m.id for m in self.messages) + 1)
                return
            except Exception:
                log.exception("chats.json повреждён — пересоздаю")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "messages": [m.to_dict() for m in self.messages[-MAX_MESSAGES:]],
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".chats-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def reload(self) -> None:
        try:
            self._load()
        except Exception:
            log.exception("reload chats.json не удался")

    # ---------- запись ----------

    def add_message(self, chat_id: int, text: str, direction: str) -> ConvoMsg:
        m = ConvoMsg(
            id=self._next_id, chat_id=int(chat_id),
            text=(text or "").strip() or ("…" if direction == DIR_IN else ""),
            direction=direction, ts=_now(),
        )
        self._next_id += 1
        self.messages.append(m)
        if len(self.messages) > MAX_MESSAGES:
            self.messages = self.messages[-MAX_MESSAGES:]
        self._save()
        return m

    # ---------- чтение ----------

    def messages_for(self, chat_id: int, limit: int = 100) -> list[ConvoMsg]:
        out = [m for m in self.messages if m.chat_id == int(chat_id)]
        return out[-limit:]

    def summary(self) -> list[dict]:
        """По одному клиенту: последнее сообщение, количество, время (по свежести)."""
        last: dict[int, ConvoMsg] = {}
        count: dict[int, int] = {}
        for m in self.messages:
            count[m.chat_id] = count.get(m.chat_id, 0) + 1
            last[m.chat_id] = m
        out = [
            {
                "chat_id": cid,
                "count": count[cid],
                "last": last[cid].to_dict(),
            }
            for cid in last
        ]
        out.sort(key=lambda r: r["last"]["ts"], reverse=True)
        return out
