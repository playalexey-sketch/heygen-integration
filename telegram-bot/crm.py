"""CRM: база клиентов бота (JSON, общий файл — бот пишет, админка читает).

Клиент попадает в базу, когда жмёт /start (в т.ч. по ссылке ?start=КОД —
это и есть «откуда пришёл»), и обновляется при каждом сообщении.
По базе можно делать выборочные рассылки: всем / по тегу / по источнику.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("crm")


@dataclass
class ClientRec:
    id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    source: str = ""        # код из ?start= — откуда пришёл (youtube, vk, 123, ...)
    first_seen: str = ""    # ISO
    last_seen: str = ""     # ISO
    msgs: int = 0
    tags: list = field(default_factory=list)
    blocked: bool = False   # заблокировал бота (рассылка ему не доходит)

    @classmethod
    def from_dict(cls, d: dict) -> "ClientRec":
        return cls(
            id=int(d["id"]),
            username=str(d.get("username", "")),
            first_name=str(d.get("first_name", "")),
            last_name=str(d.get("last_name", "")),
            source=str(d.get("source", "")),
            first_seen=str(d.get("first_seen", "")),
            last_seen=str(d.get("last_seen", "")),
            msgs=int(d.get("msgs", 0)),
            tags=list(d.get("tags", [])),
            blocked=bool(d.get("blocked", False)),
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


class CrmStorage:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.users: dict[int, ClientRec] = {}
        self._load()

    # ---------- загрузка / сохранение ----------

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for _, d in (data.get("users") or {}).items():
                    rec = ClientRec.from_dict(d)
                    self.users[rec.id] = rec
                return
            except Exception:
                log.exception("crm.json повреждён — пересоздаю")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"users": {str(u.id): asdict(u) for u in self.users.values()}}
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".crm-")
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
            log.exception("reload crm.json не удался")

    # ---------- запись (процесс бота) ----------

    def upsert(self, user, source: Optional[str] = None) -> ClientRec:
        """Зарегистрировать/обновить клиента (user — aiogram.types.User)."""
        uid = user.id
        now = _now()
        rec = self.users.get(uid)
        if rec is None:
            rec = ClientRec(id=uid, first_seen=now, last_seen=now)
            self.users[uid] = rec
        rec.username = getattr(user, "username", None) or rec.username
        rec.first_name = getattr(user, "first_name", None) or rec.first_name
        rec.last_name = getattr(user, "last_name", None) or rec.last_name
        rec.last_seen = now
        if source:
            rec.source = source  # последняя известная точка входа
        self._save()
        return rec

    def touch(self, uid: int) -> None:
        rec = self.users.get(uid)
        if rec is None:
            return
        rec.last_seen = _now()
        rec.msgs += 1
        self._save()

    # ---------- чтение (админка) ----------

    def get(self, uid) -> Optional[ClientRec]:
        try:
            return self.users.get(int(uid))
        except (TypeError, ValueError):
            return None

    def all(self) -> list[ClientRec]:
        return sorted(self.users.values(), key=lambda r: r.last_seen, reverse=True)

    def by_tag(self, tag: str) -> list[ClientRec]:
        t = tag.strip().lower()
        return [u for u in self.users.values() if t in [x.lower() for x in u.tags]]

    def by_source(self, source: str) -> list[ClientRec]:
        s = source.strip().lower()
        return [u for u in self.users.values() if u.source.lower() == s]

    def add_tag(self, uid, tag: str) -> Optional[ClientRec]:
        rec = self.get(uid)
        if rec is None:
            return None
        tag = tag.strip().lstrip("#")
        if tag and tag not in rec.tags:
            rec.tags.append(tag)
            self._save()
        return rec

    def remove_tag(self, uid, tag: str) -> Optional[ClientRec]:
        rec = self.get(uid)
        if rec is None:
            return None
        tag = tag.strip().lstrip("#")
        if tag in rec.tags:
            rec.tags.remove(tag)
            self._save()
        return rec

    def mark_blocked(self, uid) -> None:
        rec = self.get(uid)
        if rec is not None and not rec.blocked:
            rec.blocked = True
            self._save()

    # ---------- статистика ----------

    def sources_stats(self) -> dict:
        out: dict = {}
        for u in self.users.values():
            key = u.source or "(без кода)"
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def tags_stats(self) -> dict:
        out: dict = {}
        for u in self.users.values():
            for t in u.tags:
                out[t] = out.get(t, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
