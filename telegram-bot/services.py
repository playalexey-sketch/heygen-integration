"""Админы: кто имеет доступ к панели и видит ВСЕ сообщения клиентов.

Источники админов:
1. ADMIN_ID из .env — постоянные (менять только в файле);
2. bot_data/admins.json — добавленные командой /addadmin в боте
   (переживают перезапуск, удаляются /delpadmin).

Админ видит: пересылку всех сообщений клиентов, все команды управления,
CRM, рассылки. Клиент админа — обычный клиент (его /start не запускает сценарий).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("admin")


class AdminService:
    def __init__(self, ids: frozenset | set, path: Path | str | None = None):
        self._ids: set[int] = set(ids)
        self._env_ids: set[int] = set(ids)  # из .env — нельзя удалить командой
        self._path = Path(path) if path else None
        self._locked = bool(ids)
        self._load_file()
        if self._ids:
            self._locked = True

    # ---------- файл admins.json ----------

    def _load_file(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for x in data.get("admins", []):
                self._ids.add(int(x))
        except Exception:
            log.exception("admins.json повреждён — игнорирую")

    def _save_file(self) -> None:
        if not self._path:
            return
        file_admins = sorted(self._ids - self._env_ids)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"admins": file_admins}
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".admins-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------- API ----------

    def is_admin(self, user_id: int) -> bool:
        return user_id in self._ids

    def allow_anyone(self) -> bool:
        """Режим «открыт»: админов пока нет — первый /admin станет админом."""
        return not self._locked

    def promote(self, user_id: int) -> None:
        self._ids.add(user_id)
        self._locked = True
        self._save_file()
        log.warning("ADMIN_ID не был задан — первый пользователь %s стал админом", user_id)

    def add_admin(self, user_id: int) -> None:
        uid = int(user_id)
        self._ids.add(uid)
        self._locked = True
        self._save_file()
        log.info("Админ добавлен: %s", uid)

    def remove_admin(self, user_id: int) -> bool:
        """Удаляет только админа из admins.json; из .env — только правкой .env."""
        uid = int(user_id)
        if uid in self._env_ids:
            return False
        if uid not in self._ids:
            return False
        self._ids.discard(uid)
        self._save_file()
        if not self._ids:
            self._locked = False  # админов не осталось — режим «открыт»
        log.info("Админ удалён: %s", uid)
        return True

    def list_admins(self) -> list[dict]:
        return [{"id": uid, "from_env": uid in self._env_ids} for uid in sorted(self._ids)]
