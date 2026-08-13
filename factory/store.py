# -*- coding: utf-8 -*-
"""Простое JSON-хранилище: агенты, фабрики, прогоны, настройки."""

from __future__ import annotations

import json
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import presets

DATA_DIR = Path(__file__).resolve().parent.parent / "factory_data"


def _now() -> float:
    return time.time()


def nid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else DATA_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_defaults()

    def _path(self, name: str) -> Path:
        return self.root / name

    def _read(self, name: str, default: Any) -> Any:
        path = self._path(name)
        if not path.exists():
            return deepcopy(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return deepcopy(default)

    def _write(self, name: str, data: Any) -> None:
        path = self._path(name)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _ensure_defaults(self) -> None:
        with self._lock:
            if not self._path("settings.json").exists():
                self._write(
                    "settings.json",
                    {
                        "base_url": "",
                        "api_key": "lm-studio",
                        "model": "",
                        "backend": "auto",
                        "timeout": 180,
                    },
                )
            if not self._path("agents.json").exists():
                agents = []
                for raw in presets.AGENTS:
                    item = dict(raw)
                    item["created_at"] = _now()
                    item["builtin"] = True
                    agents.append(item)
                self._write("agents.json", agents)
            if not self._path("factories.json").exists():
                factories = []
                for raw in presets.FACTORIES:
                    item = dict(raw)
                    item["created_at"] = _now()
                    item["builtin"] = True
                    factories.append(item)
                self._write("factories.json", factories)

    # --- settings ---
    def get_settings(self) -> dict:
        with self._lock:
            return self._read("settings.json", {})

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            cur = self._read("settings.json", {})
            for key in ("base_url", "api_key", "model", "backend", "timeout"):
                if key in patch and patch[key] is not None:
                    cur[key] = patch[key]
            self._write("settings.json", cur)
            return cur

    # --- agents ---
    def list_agents(self) -> list[dict]:
        with self._lock:
            return self._read("agents.json", [])

    def get_agent(self, agent_id: str) -> dict | None:
        for item in self.list_agents():
            if item.get("id") == agent_id:
                return item
        return None

    def save_agent(self, payload: dict) -> dict:
        with self._lock:
            items = self._read("agents.json", [])
            agent_id = payload.get("id") or nid("agt")
            found = None
            for i, item in enumerate(items):
                if item.get("id") == agent_id:
                    found = i
                    break
            agent = {
                "id": agent_id,
                "name": (payload.get("name") or "Агент").strip(),
                "emoji": (payload.get("emoji") or "🤖").strip()[:4],
                "role": (payload.get("role") or "custom").strip(),
                "color": payload.get("color") or "#5b8cff",
                "style": (payload.get("style") or "").strip(),
                "system": (payload.get("system") or "").strip(),
                "builtin": False,
                "created_at": _now(),
            }
            if found is None:
                items.append(agent)
            else:
                agent["created_at"] = items[found].get("created_at", _now())
                agent["builtin"] = bool(items[found].get("builtin"))
                items[found] = agent
            self._write("agents.json", items)
            return agent

    def delete_agent(self, agent_id: str) -> bool:
        with self._lock:
            items = self._read("agents.json", [])
            keep = [a for a in items if a.get("id") != agent_id]
            if len(keep) == len(items):
                return False
            self._write("agents.json", keep)
            return True

    # --- factories ---
    def list_factories(self) -> list[dict]:
        with self._lock:
            return self._read("factories.json", [])

    def get_factory(self, factory_id: str) -> dict | None:
        for item in self.list_factories():
            if item.get("id") == factory_id:
                return item
        return None

    def save_factory(self, payload: dict) -> dict:
        with self._lock:
            items = self._read("factories.json", [])
            factory_id = payload.get("id") or nid("fac")
            found = None
            for i, item in enumerate(items):
                if item.get("id") == factory_id:
                    found = i
                    break
            factory = {
                "id": factory_id,
                "name": (payload.get("name") or "Фабрика").strip(),
                "goal": (payload.get("goal") or "").strip(),
                "agent_ids": list(payload.get("agent_ids") or []),
                "mode": payload.get("mode") or "round_robin",
                "max_rounds": int(payload.get("max_rounds") or 5),
                "auto_continue": bool(payload.get("auto_continue")),
                "max_tokens": int(payload.get("max_tokens") or 180),
                "temperature": float(payload.get("temperature") or 0.7),
                "builtin": False,
                "created_at": _now(),
            }
            if found is None:
                items.append(factory)
            else:
                factory["created_at"] = items[found].get("created_at", _now())
                factory["builtin"] = bool(items[found].get("builtin"))
                items[found] = factory
            self._write("factories.json", items)
            return factory

    def delete_factory(self, factory_id: str) -> bool:
        with self._lock:
            items = self._read("factories.json", [])
            keep = [f for f in items if f.get("id") != factory_id]
            if len(keep) == len(items):
                return False
            self._write("factories.json", keep)
            return True

    # --- runs ---
    def _run_path(self, run_id: str) -> Path:
        return self.root / "runs" / f"{run_id}.json"

    def list_runs(self) -> list[dict]:
        with self._lock:
            rows = []
            for path in sorted((self.root / "runs").glob("*.json"), reverse=True):
                try:
                    rows.append(json.loads(path.read_text(encoding="utf-8")))
                except Exception:
                    continue
            return rows

    def get_run(self, run_id: str) -> dict | None:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def create_run(self, factory: dict, brief: str = "") -> dict:
        run = {
            "id": nid("run"),
            "factory_id": factory["id"],
            "factory_name": factory.get("name"),
            "goal": factory.get("goal") or "",
            "brief": brief.strip(),
            "mode": factory.get("mode") or "round_robin",
            "agent_ids": list(factory.get("agent_ids") or []),
            "max_rounds": int(factory.get("max_rounds") or 5),
            "auto_continue": bool(factory.get("auto_continue")),
            "max_tokens": int(factory.get("max_tokens") or 180),
            "temperature": float(factory.get("temperature") or 0.7),
            "status": "idle",
            "round": 0,
            "turn": 0,
            "speaking": None,
            "partial": "",
            "messages": [],
            "events": [],
            "summary": "",
            "error": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.save_run(run)
        return run

    def save_run(self, run: dict) -> dict:
        with self._lock:
            run["updated_at"] = _now()
            path = self._run_path(run["id"])
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return run

    def patch_run(self, run_id: str, **fields: Any) -> dict | None:
        with self._lock:
            run = self.get_run(run_id)
            if not run:
                return None
            run.update(fields)
            return self.save_run(run)

    def add_message(self, run_id: str, message: dict) -> dict | None:
        with self._lock:
            run = self.get_run(run_id)
            if not run:
                return None
            msg = dict(message)
            msg.setdefault("id", nid("msg"))
            msg.setdefault("ts", _now())
            run["messages"].append(msg)
            run["partial"] = ""
            return self.save_run(run)

    def add_event(self, run_id: str, kind: str, text: str) -> dict | None:
        with self._lock:
            run = self.get_run(run_id)
            if not run:
                return None
            run["events"].append({"ts": _now(), "kind": kind, "text": text})
            run["events"] = run["events"][-80:]
            return self.save_run(run)
