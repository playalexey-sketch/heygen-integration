"""Хранилище этапов: JSON-файл с атомарной записью.

Этап — это одна «ступень» сценария, который бот проигрывает клиенту после /start:
  * delay_seconds — сколько ждать после предыдущего сообщения бота (сек)
  * content_type  — text | link | nickname
  * content       — текст / ссылка / ник
  * enabled       — включён ли этап
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("storage")

CONTENT_TEXT = "text"
CONTENT_LINK = "link"
CONTENT_NICKNAME = "nickname"
CONTENT_TYPES = (CONTENT_TEXT, CONTENT_LINK, CONTENT_NICKNAME)

DEFAULT_WELCOME = (
    "Привет! 👋\n"
    "Рад, что вы здесь. Всё нужное я пришлю по порядку:\n"
    "сначала файл, затем — контакты и подробности.\n"
    "\n"
    "(это сообщение редактируется админом в панели /admin)"
)

DEFAULT_LINK = "https://example.com/REPLACE_THIS_LINK_WITH_YOUR_FILE"


@dataclass
class Stage:
    id: int
    delay_seconds: int
    content_type: str
    content: str
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Stage":
        return cls(
            id=int(d["id"]),
            delay_seconds=int(d.get("delay_seconds", 0)),
            content_type=d.get("content_type", CONTENT_TEXT),
            content=str(d.get("content", "")),
            enabled=bool(d.get("enabled", True)),
        )


class StageStorage:
    """Порядок списка = порядок отправки клиенту."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.stages: list[Stage] = []
        self._next_id = 1
        self._load_or_seed()

    # ---------- загрузка / сохранение ----------

    def _load_or_seed(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.stages = [Stage.from_dict(d) for d in data.get("stages", [])]
                self._next_id = int(data.get("next_id", 1))
                if self.stages:
                    self._next_id = max(self._next_id, max(s.id for s in self.stages) + 1)
                return
            except Exception:
                backup = self.path.with_suffix(".json.broken")
                try:
                    os.replace(self.path, backup)
                    log.error("stages.json повреждён, сохранён как %s — восстанавливаю стандартные этапы", backup)
                except OSError:
                    log.exception("Не удалось сделать бэкап повреждённого stages.json, пересоздаю файл")
        self._seed()

    def _seed(self) -> None:
        self.stages = [
            Stage(id=1, delay_seconds=0, content_type=CONTENT_TEXT, content=DEFAULT_WELCOME),
            Stage(id=2, delay_seconds=3, content_type=CONTENT_LINK, content=DEFAULT_LINK),
        ]
        self._next_id = 3
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"next_id": self._next_id, "stages": [s.to_dict() for s in self.stages]}
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".stages-")
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

    # ---------- чтение ----------

    def all(self) -> list[Stage]:
        return list(self.stages)

    def ordered(self) -> list[Stage]:
        """Включённые этапы в порядке отправки."""
        return [s for s in self.stages if s.enabled]

    def get(self, stage_id: int) -> Optional[Stage]:
        for s in self.stages:
            if s.id == stage_id:
                return s
        return None

    def index_of(self, stage: Stage) -> int:
        """0-индексная позиция в списке (для подсчёта номера этапа)."""
        for i, s in enumerate(self.stages):
            if s.id == stage.id:
                return i
        raise ValueError("stage not found")

    def get_by_position(self, position: int) -> Optional[Stage]:
        if 1 <= position <= len(self.stages):
            return self.stages[position - 1]
        return None

    # ---------- изменения (каждое — с сохранением) ----------

    def add(self, delay_seconds: int, content_type: str, content: str) -> Stage:
        stage = Stage(
            id=self._next_id,
            delay_seconds=delay_seconds,
            content_type=content_type,
            content=content,
        )
        self._next_id += 1
        self.stages.append(stage)
        self._save()
        return stage

    def update(self, stage_id: int, **fields) -> Optional[Stage]:
        stage = self.get(stage_id)
        if stage is None:
            return None
        allowed = {"delay_seconds", "content_type", "content", "enabled"}
        for key, value in fields.items():
            if key in allowed:
                setattr(stage, key, value)
        self._save()
        return stage

    def remove(self, stage_id: int) -> bool:
        stage = self.get(stage_id)
        if stage is None:
            return False
        self.stages.remove(stage)
        self._save()
        return True

    def toggle(self, stage_id: int) -> Optional[Stage]:
        stage = self.get(stage_id)
        if stage is None:
            return None
        return self.set_enabled(stage_id, not stage.enabled)

    def set_enabled(self, stage_id: int, value: bool) -> Optional[Stage]:
        stage = self.get(stage_id)
        if stage is None:
            return None
        stage.enabled = value
        self._save()
        return stage

    def move(self, stage_id: int, direction: int) -> bool:
        """direction: -1 — выше, +1 — ниже. Возвращает False, если некуда двигать."""
        stage = self.get(stage_id)
        if stage is None:
            return False
        i = self.index_of(stage)
        j = i + direction
        if not (0 <= j < len(self.stages)):
            return False
        self.stages[i], self.stages[j] = self.stages[j], self.stages[i]
        self._save()
        return True
