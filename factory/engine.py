# -*- coding: utf-8 -*-
"""Очередь ходов: агенты говорят по кругу, человек утверждает каждый шаг."""

from __future__ import annotations

import re
import threading
import time
from typing import Callable

from . import llm, presets
from .store import Store

EventFn = Callable[[str, dict], None]


def _overlap(a: str, b: str) -> float:
    ta = set(re.findall(r"[а-яa-z0-9]{4,}", (a or "").lower()))
    tb = set(re.findall(r"[а-яa-z0-9]{4,}", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def _clip_transcript(messages: list[dict], keep: int = 8) -> str:
    rows = []
    for msg in messages[-keep:]:
        name = msg.get("name") or msg.get("role")
        body = (msg.get("content") or "").strip()
        if not body:
            continue
        rows.append(f"{name}: {body}")
    return "\n\n".join(rows) if rows else "(пока пусто)"


class Engine:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._threads: dict[str, threading.Thread] = {}
        self._stop: dict[str, threading.Event] = {}
        self._pause: dict[str, threading.Event] = {}
        self._approve: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._listeners: dict[str, list[EventFn]] = {}

    def subscribe(self, run_id: str, fn: EventFn) -> None:
        with self._lock:
            self._listeners.setdefault(run_id, []).append(fn)

    def unsubscribe(self, run_id: str, fn: EventFn) -> None:
        with self._lock:
            lst = self._listeners.get(run_id) or []
            self._listeners[run_id] = [x for x in lst if x is not fn]

    def _emit(self, run_id: str, kind: str, payload: dict) -> None:
        with self._lock:
            listeners = list(self._listeners.get(run_id) or [])
        for fn in listeners:
            try:
                fn(kind, payload)
            except Exception:
                pass

    def start(self, factory_id: str, brief: str = "") -> dict:
        factory = self.store.get_factory(factory_id)
        if not factory:
            raise ValueError("Фабрика не найдена")
        if len(factory.get("agent_ids") or []) < 2:
            raise ValueError("Нужно минимум два агента")
        run = self.store.create_run(factory, brief=brief)
        self._stop[run["id"]] = threading.Event()
        self._pause[run["id"]] = threading.Event()
        self._approve[run["id"]] = threading.Event()
        if factory.get("auto_continue"):
            self._approve[run["id"]].set()
        intro = (
            f"Цель фабрики: {factory.get('goal') or '—'}\n"
            f"Режим: {factory.get('mode')}\n"
            f"Агентов: {len(factory.get('agent_ids') or [])}"
        )
        if brief.strip():
            intro += f"\nУстановка руководителя: {brief.strip()}"
        self.store.add_message(
            run["id"],
            {
                "role": "system",
                "name": "Фабрика",
                "agent_id": "system",
                "color": "#8b96ab",
                "emoji": "🏭",
                "content": intro,
                "round": 0,
            },
        )
        self.store.add_event(run["id"], "start", "Прогон создан. Жду первый ход.")
        self.store.patch_run(run["id"], status="waiting_supervisor" if not factory.get("auto_continue") else "running")
        thread = threading.Thread(target=self._loop, args=(run["id"],), daemon=True)
        self._threads[run["id"]] = thread
        thread.start()
        self._emit(run["id"], "status", self.store.get_run(run["id"]) or {})
        return self.store.get_run(run["id"])  # type: ignore[return-value]

    def approve(self, run_id: str) -> dict | None:
        ev = self._approve.get(run_id)
        if ev:
            ev.set()
        self.store.add_event(run_id, "approve", "Руководитель разрешил следующий ход")
        run = self.store.get_run(run_id)
        if run and run.get("status") in ("waiting_supervisor", "paused", "idle"):
            self.store.patch_run(run_id, status="running")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        return self.store.get_run(run_id)

    def pause(self, run_id: str) -> dict | None:
        ev = self._pause.get(run_id)
        if ev:
            ev.set()
        self.store.patch_run(run_id, status="paused")
        self.store.add_event(run_id, "pause", "Пауза")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        return self.store.get_run(run_id)

    def resume(self, run_id: str) -> dict | None:
        ev = self._pause.get(run_id)
        if ev:
            ev.clear()
        # «Дальше сами»: отпускаем очередь без кнопки на каждый ход
        self.store.patch_run(run_id, status="running", auto_continue=True)
        appr = self._approve.get(run_id)
        if appr:
            appr.set()
        self.store.add_event(run_id, "resume", "Агенты идут сами, без кнопки на каждый ход")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        return self.store.get_run(run_id)

    def stop(self, run_id: str) -> dict | None:
        ev = self._stop.get(run_id)
        if ev:
            ev.set()
        appr = self._approve.get(run_id)
        if appr:
            appr.set()
        pause = self._pause.get(run_id)
        if pause:
            pause.clear()
        self.store.patch_run(run_id, status="stopped", speaking=None, partial="")
        self.store.add_event(run_id, "stop", "Руководитель остановил фабрику")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        return self.store.get_run(run_id)

    def inject(self, run_id: str, text: str) -> dict | None:
        text = (text or "").strip()
        if not text:
            raise ValueError("Пустое указание")
        run = self.store.add_message(
            run_id,
            {
                "role": "supervisor",
                "name": "Руководитель",
                "agent_id": "supervisor",
                "color": "#f5c16c",
                "emoji": "👁️",
                "content": text,
                "round": (self.store.get_run(run_id) or {}).get("round") or 0,
            },
        )
        self.store.add_event(run_id, "inject", "Указание руководителя добавлено в стенограмму")
        self._emit(run_id, "message", (run or {}).get("messages", [None])[-1] or {})
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        return self.store.get_run(run_id)

    def summarize(self, run_id: str) -> dict | None:
        run = self.store.get_run(run_id)
        if not run:
            return None
        settings = self.store.get_settings()
        transcript = _clip_transcript(run.get("messages") or [], keep=16)
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты секретарь совещания. Собери итог: решение, шаги, риски, открытые вопросы. "
                    "6–10 коротких пунктов. Без воды."
                ),
            },
            {
                "role": "user",
                "content": f"Цель: {run.get('goal')}\n\nСтенограмма:\n{transcript}",
            },
        ]
        acc: list[str] = []

        def on_token(delta: str) -> None:
            acc.append(delta)
            self.store.patch_run(run_id, partial="".join(acc), speaking="summary")
            self._emit(run_id, "token", {"text": "".join(acc), "speaking": "summary"})

        try:
            text = llm.chat(messages, settings=settings, temperature=0.3, max_tokens=280, on_token=on_token)
        except Exception as exc:
            text = f"Не удалось собрать итог: {exc}"
        self.store.patch_run(run_id, summary=text, partial="", speaking=None)
        self.store.add_message(
            run_id,
            {
                "role": "summary",
                "name": "Итог",
                "agent_id": "summary",
                "color": "#3ee0b0",
                "emoji": "📌",
                "content": text,
                "round": run.get("round") or 0,
            },
        )
        self.store.add_event(run_id, "summary", "Итог собран")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        return self.store.get_run(run_id)

    def _agents(self, run: dict) -> list[dict]:
        out = []
        for aid in run.get("agent_ids") or []:
            agent = self.store.get_agent(aid)
            if agent:
                out.append(agent)
        return out

    def _wait_gate(self, run_id: str) -> bool:
        """True = можно говорить. False = остановлены."""
        stop = self._stop[run_id]
        pause = self._pause[run_id]
        approve = self._approve[run_id]
        run = self.store.get_run(run_id) or {}
        if run.get("auto_continue"):
            while pause.is_set() and not stop.is_set():
                time.sleep(0.15)
            return not stop.is_set()
        # ручной режим: каждый ход ждёт кнопку «Далее»
        approve.clear()
        self.store.patch_run(run_id, status="waiting_supervisor", speaking=None, partial="")
        self.store.add_event(run_id, "wait", "Жду разрешения руководителя на следующий ход")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})
        while not stop.is_set():
            if pause.is_set():
                time.sleep(0.15)
                continue
            if approve.wait(timeout=0.2):
                approve.clear()
                self.store.patch_run(run_id, status="running")
                self._emit(run_id, "status", self.store.get_run(run_id) or {})
                return True
        return False

    def _build_messages(self, run: dict, agent: dict, agents: list[dict]) -> list[dict]:
        others = ", ".join(f"{a.get('emoji', '')} {a['name']}" for a in agents if a["id"] != agent["id"])
        mode = run.get("mode") or "round_robin"
        mode_hint = {
            "round_robin": "Говорите по очереди. Развивайте мысль, не пересказывайте предыдущего.",
            "debate": "Это спор. Защищайте свою роль, но ищите точку, где можно договориться.",
            "pipeline": "Это конвейер. Возьмите последний полезный кусок и превратите его в свой артефакт.",
        }.get(mode, "")
        system = (
            f"Ты {agent.get('name')}. {agent.get('system') or ''}\n"
            f"Стиль: {agent.get('style') or 'коротко'}.\n"
            f"Общая цель команды: {run.get('goal')}\n"
            f"С тобой работают: {others}.\n"
            f"{mode_hint}\n"
            "Правила: 4–8 коротких предложений; не повторяй чужие реплики; "
            "дай один конкретный следующий шаг; не говори, что ты ИИ."
        )
        if run.get("brief"):
            system += f"\nУстановка руководителя: {run['brief']}"
        transcript = _clip_transcript(run.get("messages") or [], keep=8)
        user = (
            f"Раунд {run.get('round', 0) + 1} из {run.get('max_rounds')}. "
            f"Сейчас твоя очередь, {agent.get('name')}.\n\n"
            f"Стенограмма:\n{transcript}\n\n"
            "Ответь по своей роли."
        )
        if mode == "pipeline":
            last = None
            for msg in reversed(run.get("messages") or []):
                if msg.get("role") == "assistant":
                    last = msg
                    break
            if last:
                user += (
                    f"\n\nВход с предыдущего стола ({last.get('name')}):\n{last.get('content')}\n"
                    "Переработай это в свой результат."
                )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _loop(self, run_id: str) -> None:
        try:
            self._run_loop(run_id)
        except Exception as exc:
            self.store.patch_run(run_id, status="error", error=str(exc), speaking=None, partial="")
            self.store.add_event(run_id, "error", str(exc))
            self._emit(run_id, "error", {"error": str(exc)})
            self._emit(run_id, "status", self.store.get_run(run_id) or {})

    def _run_loop(self, run_id: str) -> None:
        stop = self._stop[run_id]
        settings = self.store.get_settings()
        while not stop.is_set():
            run = self.store.get_run(run_id)
            if not run:
                return
            agents = self._agents(run)
            if not agents:
                raise RuntimeError("У фабрики не осталось живых агентов")
            if run.get("round", 0) >= int(run.get("max_rounds") or 5):
                self._finish(run_id, "Достигнут лимит раундов")
                return
            if not self._wait_gate(run_id):
                return
            run = self.store.get_run(run_id) or run
            idx = int(run.get("turn") or 0) % len(agents)
            agent = agents[idx]
            self.store.patch_run(
                run_id,
                status="running",
                speaking=agent["id"],
                partial="",
                error="",
            )
            self.store.add_event(run_id, "speak", f"Говорит {agent.get('emoji', '')} {agent['name']}")
            self._emit(run_id, "status", self.store.get_run(run_id) or {})

            messages = self._build_messages(run, agent, agents)
            acc: list[str] = []

            def on_token(delta: str, _aid=agent["id"]) -> None:
                acc.append(delta)
                text = "".join(acc)
                self.store.patch_run(run_id, partial=text, speaking=_aid)
                self._emit(run_id, "token", {"text": text, "speaking": _aid})

            try:
                text = llm.chat(
                    messages,
                    settings=settings,
                    temperature=float(run.get("temperature") or 0.7),
                    max_tokens=int(run.get("max_tokens") or 180),
                    on_token=on_token,
                )
            except Exception as exc:
                self.store.patch_run(run_id, status="error", error=str(exc), speaking=None, partial="")
                self.store.add_event(run_id, "error", str(exc))
                self._emit(run_id, "error", {"error": str(exc)})
                self._emit(run_id, "status", self.store.get_run(run_id) or {})
                return

            text = (text or "").strip() or "…"
            prev_assist = [
                m.get("content") or ""
                for m in (run.get("messages") or [])
                if m.get("role") == "assistant"
            ]
            if prev_assist and _overlap(text, prev_assist[-1]) > 0.72:
                text += "\n\n(повтор обрезан: скажи один новый шаг, не пересказывай прошлое)"

            self.store.add_message(
                run_id,
                {
                    "role": "assistant",
                    "name": agent.get("name"),
                    "agent_id": agent["id"],
                    "color": agent.get("color"),
                    "emoji": agent.get("emoji"),
                    "content": text,
                    "round": int(run.get("round") or 0) + 1,
                },
            )
            next_turn = int(run.get("turn") or 0) + 1
            next_round = int(run.get("round") or 0)
            if next_turn % len(agents) == 0:
                next_round += 1
            self.store.patch_run(
                run_id,
                turn=next_turn,
                round=next_round,
                speaking=None,
                partial="",
            )
            fresh = self.store.get_run(run_id) or {}
            last = (fresh.get("messages") or [None])[-1] or {}
            self._emit(run_id, "message", last)
            self._emit(run_id, "status", fresh)
            if re.search(r"\b(фабрика:стоп|итог:готово)\b", text, re.I):
                self._finish(run_id, "Агент предложил остановиться")
                return

    def _finish(self, run_id: str, why: str) -> None:
        self.store.patch_run(run_id, status="done", speaking=None, partial="")
        self.store.add_event(run_id, "done", why)
        try:
            self.summarize(run_id)
        except Exception as exc:
            self.store.add_event(run_id, "error", f"Итог не собрался: {exc}")
        self.store.patch_run(run_id, status="done")
        self._emit(run_id, "status", self.store.get_run(run_id) or {})


def chat_system_messages(history: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": presets.CHAT_SYSTEM}]
    for msg in history[-16:]:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out
