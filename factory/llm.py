# -*- coding: utf-8 -*-
"""Клиент к локальным OpenAI-совместимым серверам + демо-режим без модели."""

from __future__ import annotations

import json
import random
import re
from typing import Callable, Iterable
from urllib.parse import urlparse

import requests

BACKENDS = [
    {
        "id": "lmstudio",
        "name": "LM Studio / Bionic runtime",
        "base_url": "http://127.0.0.1:1234/v1",
        "hint": "Developer → Start server, либо: lms server start --port 1234",
    },
    {
        "id": "llamacpp",
        "name": "llama.cpp server",
        "base_url": "http://127.0.0.1:8080/v1",
        "hint": "llama-server -m model.gguf --port 8080",
    },
    {
        "id": "ollama",
        "name": "Ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "hint": "ollama serve  +  модель из GGUF через Modelfile",
    },
]

TokenCb = Callable[[str], None]


def _normalize_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith("http"):
        url = "http://" + url
    if url.endswith("/v1"):
        return url
    # Ollama native is :11434 without /v1; OpenAI compat is /v1
    return url + "/v1"


def probe(base_url: str, timeout: float = 1.4) -> dict:
    base = _normalize_base(base_url)
    info = {"ok": False, "base_url": base, "models": [], "error": ""}
    if not base:
        info["error"] = "пустой URL"
        return info
    try:
        r = requests.get(f"{base}/models", timeout=timeout)
        if r.status_code != 200:
            info["error"] = f"HTTP {r.status_code}"
            return info
        data = r.json()
        models = []
        for item in data.get("data") or []:
            mid = item.get("id") or item.get("name")
            if mid:
                models.append(mid)
        info["ok"] = True
        info["models"] = models
        return info
    except requests.exceptions.ConnectionError:
        info["error"] = "нет соединения"
        return info
    except Exception as exc:
        info["error"] = str(exc)[:160]
        return info


def detect_backends() -> list[dict]:
    found = []
    for spec in BACKENDS:
        result = probe(spec["base_url"])
        row = dict(spec)
        row.update(result)
        found.append(row)
    return found


def pick_backend(settings: dict) -> dict:
    """Выбрать живой бэкенд. Если ничего нет — mock."""
    wanted = (settings.get("backend") or "auto").strip().lower()
    custom = _normalize_base(settings.get("base_url") or "")
    if wanted == "mock":
        return {"id": "mock", "name": "Демо без модели", "base_url": "", "ok": True, "models": ["mock-qwen"]}
    if custom and wanted in ("auto", "custom"):
        result = probe(custom)
        result.update({"id": "custom", "name": "Свой URL", "hint": custom})
        if result["ok"]:
            return result
    detected = detect_backends()
    if wanted != "auto":
        for row in detected:
            if row["id"] == wanted:
                return row
    for row in detected:
        if row.get("ok"):
            return row
    return {
        "id": "mock",
        "name": "Демо без модели",
        "base_url": "",
        "ok": True,
        "models": ["mock-qwen"],
        "hint": "Ни один локальный сервер не ответил. Включён демо-режим.",
    }


def choose_model(backend: dict, preferred: str = "") -> str:
    if preferred:
        return preferred
    models = backend.get("models") or []
    if not models:
        return "local-model"
    # предпочитаем qwen, если он уже загружен
    for m in models:
        if "qwen" in m.lower():
            return m
    return models[0]


def chat(
    messages: list[dict],
    *,
    settings: dict,
    temperature: float = 0.7,
    max_tokens: int = 180,
    on_token: TokenCb | None = None,
) -> str:
    backend = pick_backend(settings)
    if backend.get("id") == "mock" or not backend.get("base_url"):
        return mock_chat(messages, on_token=on_token)

    model = choose_model(backend, settings.get("model") or "")
    timeout = int(settings.get("timeout") or 180)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.get('api_key') or 'lm-studio'}",
    }
    url = backend["base_url"].rstrip("/") + "/chat/completions"
    try:
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=timeout) as resp:
            if resp.status_code != 200:
                # часть серверов не любит stream=True — повторим без стрима
                payload["stream"] = False
                resp2 = requests.post(url, json=payload, headers=headers, timeout=timeout)
                if resp2.status_code != 200:
                    raise RuntimeError(f"LLM HTTP {resp2.status_code}: {resp2.text[:400]}")
                data = resp2.json()
                text = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if on_token and text:
                    on_token(text)
                return (text or "").strip()
            acc = []
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue
                delta = (
                    (chunk.get("choices") or [{}])[0]
                    .get("delta", {})
                    .get("content")
                )
                if not delta:
                    delta = (
                        (chunk.get("choices") or [{}])[0]
                        .get("message", {})
                        .get("content")
                    )
                if delta:
                    acc.append(delta)
                    if on_token:
                        on_token(delta)
            return "".join(acc).strip()
    except Exception as exc:
        raise RuntimeError(f"Нет ответа от модели ({backend.get('name')}): {exc}") from exc


def mock_chat(messages: list[dict], on_token: TokenCb | None = None) -> str:
    """Короткий ролевой ответ без настоящей модели — чтобы увидеть фабрику."""
    system = ""
    last_user = ""
    last_other = ""
    for msg in messages:
        if msg.get("role") == "system":
            system += " " + (msg.get("content") or "")
        elif msg.get("role") == "user":
            last_user = msg.get("content") or ""
        elif msg.get("role") == "assistant":
            last_other = msg.get("content") or ""

    name = "Агент"
    m = re.search(r"Ты ([^.!\n]+)", system)
    if m:
        name = m.group(1).strip()[:40]

    goal = ""
    gm = re.search(r"Общая цель команды:\s*(.+)", system)
    if not gm:
        gm = re.search(r"цель[^\n]*:\s*(.+)", last_user + "\n" + system, re.I)
    if gm:
        goal = gm.group(1).strip()[:120]
    if not goal:
        goal = "поставленная задача"

    # Только имя и первая строка — иначе чужие роли в «с тобой работают» сбивают голос
    role_key = "generic"
    low = (name + " " + system.split("\n", 1)[0]).lower()
    if "исследоват" in low or "research" in low:
        role_key = "researcher"
    elif "критик" in low or "critic" in low:
        role_key = "critic"
    elif "писател" in low or "writer" in low:
        role_key = "writer"
    elif "планиров" in low or "planner" in low:
        role_key = "planner"
    elif "инженер" in low or "engineer" in low:
        role_key = "engineer"
    elif "скептик" in low or "skeptic" in low:
        role_key = "skeptic"
    elif "ведущ" in low or "host" in low:
        role_key = "host"

    lines = {
        "researcher": [
            f"По цели «{goal}» я бы не бросался в реализацию.",
            "Сначала сниму три неизвестных: кому это нужно, какой самый маленький прототип, чем измерим успех.",
            "Варианты: сделать узкий пилот на одну неделю; украсть чужой рабочий шаблон и урезать; вообще отказаться, если нет заказчика.",
            "Предлагаю сегодня проверить спрос одним разговором или коротким объявлением — без кода.",
        ],
        "critic": [
            f"Слабое место цели «{goal}» — она звучит шире, чем есть силы.",
            "Риск: команда начнёт спорить красиво и не сделает ни одного проверяемого шага.",
            "Ещё риск: 1.5B-модель будет уверенно выдумывать факты, если её не резать короткими ходами.",
            "Чиним так: один критерий успеха, один пилот, стоп-слово если через 3 раунда нет конкретного действия.",
        ],
        "writer": [
            f"Черновик для людей, без канцелярита:",
            f"«Мы берём «{goal}» и за неделю делаем самый тонкий рабочий кусок.",
            "Не платформу. Не экосистему. Один сценарий, который можно показать руками».",
            "Если нужно — следующим ходом сверстаю это в короткий бриф на полстраницы.",
        ],
        "planner": [
            "План на неделю, без воды:",
            "1) Сегодня — сформулировать одного пользователя и одну сцену успеха.",
            "2) Завтра — набросать каркас (чат / фабрика / отчёт) и что сознательно не делаем.",
            "3) Через 3 дня — живой прогон с вами за пультом.",
            "4) В конце недели — оставить только то, что сработало, и выкинуть остальное.",
        ],
        "engineer": [
            "Собирать это надо как три коробки: модель (GGUF через LM Studio), чат, фабрика ходов.",
            "Не тащить оркестраторы на 20 библиотек — для 1.5B они только шумят.",
            "Технический минимум: OpenAI-совместимый :1234, очередь раундов, кнопка «ещё ход» у человека.",
            "Если модель тупит — режем max_tokens до 160 и не даём больше трёх агентов.",
        ],
        "skeptic": [
            "Откуда мы знаем, что фабрика агентов вообще нужна, а не обычный чат с чек-листом?",
            "Если после двух кругов агенты повторяют одно и то же — это не мышление, это эхо.",
            "Критерий: появился артефакт (план, текст, список задач), который человек готов взять в работу.",
            "Иначе останавливаем и меняем цель, а не добавляем четвёртого агента.",
        ],
        "host": [
            "Что уже ясно: цель есть, ролей хватает, спор полезный.",
            "Где дыра: ещё нет одного следующего действия с владельцем и сроком.",
            "Сейчас логично услышать конкретного шага на сегодня, без новых идей.",
            "Вопрос команде: какой самый маленький шаг можно сделать за 30 минут?",
        ],
        "generic": [
            f"Я {name}. Держу фокус на «{goal}».",
            "Не раздуваю объём. Беру уже сказанное и сдвигаю на шаг вперёд.",
            "Предлагаю зафиксировать одно решение и проверить его на практике, а не плодить роли.",
        ],
    }
    text = " ".join(lines.get(role_key, lines["generic"]))
    if last_other and random.random() < 0.25:
        text += " Учту предыдущую реплику и не буду её пересказывать."
    if on_token:
        # имитируем печать кусками
        buf = ""
        for word in text.split(" "):
            piece = ((" " if buf else "") + word)
            buf += piece
            on_token(piece if buf != word else word)
    return text


def host_label(url: str) -> str:
    try:
        p = urlparse(url)
        return p.netloc or url
    except Exception:
        return url
