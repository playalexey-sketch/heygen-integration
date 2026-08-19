"""Кто есть кто: логика доступа к админ-панели."""
from __future__ import annotations

import logging

log = logging.getLogger("admin")


class AdminService:
    """
    * ADMIN_ID задан в .env — панель доступна только этим ID (режим «закрыт»).
    * ADMIN_ID пуст — первый, кто пришлёт /admin в личке, становится админом
      (режим «открыт», один раз, затем панель закрывается).
    """

    def __init__(self, ids: frozenset | set):
        self._ids: set[int] = set(ids)
        self._locked: bool = bool(ids)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self._ids

    def allow_anyone(self) -> bool:
        return not self._locked

    def promote(self, user_id: int) -> None:
        self._ids.add(user_id)
        self._locked = True
        log.warning("ADMIN_ID не был задан — первый пользователь %s стал админом бота", user_id)
