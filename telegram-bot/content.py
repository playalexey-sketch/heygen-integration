"""Медиафайлы (видео/аудио/картинки/документы) и правила «ключевое слово -> контент».

Хранятся в bot_data/content.json + папке bot_data/media/.
Бот и веб-админка — разные процессы, источник правды — файл на диске.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("content")

# виды загружаемых файлов
KIND_PHOTO = "photo"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_DOCUMENT = "document"
KINDS = (KIND_PHOTO, KIND_VIDEO, KIND_AUDIO, KIND_DOCUMENT)

# режимы совпадения триггера
MATCH_EXACT = "exact"      # точное совпадение входа
MATCH_CONTAINS = "contains"  # вход содержит триггер

KIND_ICONS = {
    KIND_PHOTO: "🖼",
    KIND_VIDEO: "🎬",
    KIND_AUDIO: "🎵",
    KIND_DOCUMENT: "📎",
}


@dataclass
class Media:
    id: int
    filename: str   # имя файла в папке media/
    name: str       # исходное имя (для отправки в Telegram)
    kind: str       # photo | video | audio | document
    size: int = 0

    def path(self, media_dir: Path) -> Path:
        return media_dir / self.filename


@dataclass
class Rule:
    id: int
    trigger: str
    match: str = MATCH_EXACT
    content_type: str = "text"
    content: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            id=int(d["id"]),
            trigger=str(d.get("trigger", "")),
            match=d.get("match", MATCH_EXACT),
            content_type=d.get("content_type", "text"),
            content=str(d.get("content", "")),
            enabled=bool(d.get("enabled", True)),
        )


def guess_kind(filename: str, mime: str = "") -> str:
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return KIND_PHOTO
    if mime.startswith("video/"):
        return KIND_VIDEO
    if mime.startswith("audio/"):
        return KIND_AUDIO
    ext = Path(filename).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return KIND_PHOTO
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return KIND_VIDEO
    if ext in {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus"}:
        return KIND_AUDIO
    return KIND_DOCUMENT


def safe_name(name: str) -> str:
    name = (name or "file").replace("\\", "_")
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name[:120] or "file"


class ContentStorage:
    """Медиа + правила. Атомарная запись JSON, файлы — в media/."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.media_dir = self.path.parent / "media"
        self.media: list[Media] = []
        self.rules: list[Rule] = []
        self._next_id = 1
        self._load_or_init()

    # ---------- загрузка / сохранение ----------

    def _load_or_init(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.media = [
                    Media(
                        id=int(m["id"]),
                        filename=m["filename"],
                        name=m.get("name", m["filename"]),
                        kind=m.get("kind", KIND_DOCUMENT),
                        size=int(m.get("size", 0)),
                    )
                    for m in data.get("media", [])
                ]
                self.rules = [Rule.from_dict(r) for r in data.get("rules", [])]
                self._next_id = int(data.get("next_id", 1))
                if self.media or self.rules:
                    self._next_id = max(
                        self._next_id,
                        max([m.id for m in self.media] + [r.id for r in self.rules] + [1]),
                    ) + 1
                return
            except Exception:
                log.exception("content.json повреждён — пересоздаю")
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "media": [asdict(m) for m in self.media],
            "rules": [r.to_dict() for r in self.rules],
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".content-")
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
        """Перечитать с диска (изменения другого процесса)."""
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.media = [
                    Media(
                        id=int(m["id"]),
                        filename=m["filename"],
                        name=m.get("name", m["filename"]),
                        kind=m.get("kind", KIND_DOCUMENT),
                        size=int(m.get("size", 0)),
                    )
                    for m in data.get("media", [])
                ]
                self.rules = [Rule.from_dict(r) for r in data.get("rules", [])]
                self._next_id = int(data.get("next_id", 1))
        except Exception:
            log.exception("reload content.json не удался")

    # ---------- медиа ----------

    def add_media(self, src: Path | str, name: str, kind: str) -> Media:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        mid = self._next_id
        self._next_id += 1
        filename = f"{mid}_{safe_name(name)}"
        dst = self.media_dir / filename
        # атомарное копирование
        suffix = Path(name).suffix
        fd, tmp = tempfile.mkstemp(dir=str(self.media_dir), suffix=suffix, prefix=f".up{mid}-")
        try:
            with open(src, "rb") as fin, os.fdopen(fd, "wb") as fout:
                while chunk := fin.read(1024 * 1024):
                    fout.write(chunk)
            os.replace(tmp, dst)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            self._next_id = mid  # откат
            raise
        m = Media(id=mid, filename=filename, name=name, kind=kind, size=dst.stat().st_size)
        self.media.append(m)
        self._save()
        return m

    def all_media(self) -> list[Media]:
        return list(self.media)

    def get_media(self, media_id) -> Optional[Media]:
        try:
            mid = int(media_id)
        except (TypeError, ValueError):
            return None
        for m in self.media:
            if m.id == mid:
                return m
        return None

    def remove_media(self, media_id: int) -> bool:
        m = self.get_media(media_id)
        if m is None:
            return False
        self.media.remove(m)
        try:
            p = m.path(self.media_dir)
            if p.exists():
                os.unlink(p)
        except OSError:
            pass
        self._save()
        return True

    # ---------- правила ----------

    def all_rules(self) -> list[Rule]:
        return list(self.rules)

    def get_rule(self, rule_id: int) -> Optional[Rule]:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None

    def index_of(self, rule: Rule) -> int:
        for i, r in enumerate(self.rules):
            if r.id == rule.id:
                return i
        raise ValueError("rule not found")

    def get_by_position(self, position: int) -> Optional[Rule]:
        if 1 <= position <= len(self.rules):
            return self.rules[position - 1]
        return None

    def add_rule(self, trigger: str, content_type: str, content: str, match: str = MATCH_EXACT) -> Rule:
        r = Rule(id=self._next_id, trigger=trigger, match=match, content_type=content_type, content=content)
        self._next_id += 1
        self.rules.append(r)
        self._save()
        return r

    def update_rule(self, rule_id: int, **fields) -> Optional[Rule]:
        r = self.get_rule(rule_id)
        if r is None:
            return None
        allowed = {"trigger", "match", "content_type", "content", "enabled"}
        for k, v in fields.items():
            if k in allowed:
                setattr(r, k, v)
        self._save()
        return r

    def remove_rule(self, rule_id: int) -> bool:
        r = self.get_rule(rule_id)
        if r is None:
            return False
        self.rules.remove(r)
        self._save()
        return True

    def toggle_rule(self, rule_id: int) -> Optional[Rule]:
        r = self.get_rule(rule_id)
        if r is None:
            return None
        r.enabled = not r.enabled
        self._save()
        return r

    def set_enabled(self, rule_id: int, value: bool) -> Optional[Rule]:
        r = self.get_rule(rule_id)
        if r is None:
            return None
        r.enabled = value
        self._save()
        return r

    def move_rule(self, rule_id: int, direction: int) -> bool:
        r = self.get_rule(rule_id)
        if r is None:
            return False
        i = self.index_of(r)
        j = i + direction
        if not (0 <= j < len(self.rules)):
            return False
        self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
        self._save()
        return True

    # ---------- поиск по входу клиента ----------

    def find_rule(self, text: str) -> Optional[Rule]:
        """Первое правило, срабатывающее на вход: сначала точные совпадения
        (по порядку списка), затем «содержит» (по порядку списка)."""
        t = (text or "").strip()
        if not t:
            return None
        for r in self.rules:
            if r.enabled and r.match == MATCH_EXACT and r.trigger.strip() == t:
                return r
        for r in self.rules:
            if r.enabled and r.match == MATCH_CONTAINS and r.trigger.strip() and r.trigger.strip() in t:
                return r
        return None
