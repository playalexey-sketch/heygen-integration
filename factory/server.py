# -*- coding: utf-8 -*-
"""Веб-пульт фабрики агентов: чат + роли + прогоны."""

from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .engine import Engine, chat_system_messages
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("FACTORY_PORT") or os.getenv("PORT") or "8003")

store = Store()
engine = Engine(store)

app = FastAPI(title="Фабрика агентов", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ok(data) -> JSONResponse:
    return JSONResponse(data)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    settings = store.get_settings()
    backends = llm.detect_backends()
    current = llm.pick_backend(settings)
    model = llm.choose_model(current, settings.get("model") or "")
    return {
        "ok": True,
        "settings": settings,
        "backends": backends,
        "current": current,
        "model": model,
        "demo": current.get("id") == "mock",
    }


@app.get("/api/settings")
def get_settings():
    return store.get_settings()


@app.put("/api/settings")
def put_settings(payload: dict):
    return store.update_settings(payload or {})


@app.get("/api/models")
def models():
    settings = store.get_settings()
    backend = llm.pick_backend(settings)
    return {
        "backend": backend,
        "models": backend.get("models") or [],
        "selected": llm.choose_model(backend, settings.get("model") or ""),
    }


@app.get("/api/agents")
def list_agents():
    return store.list_agents()


@app.post("/api/agents")
def create_agent(payload: dict):
    if not (payload.get("name") or "").strip():
        raise HTTPException(400, "Нужно имя агента")
    if not (payload.get("system") or "").strip():
        raise HTTPException(400, "Нужна роль / системный промпт")
    return store.save_agent(payload)


@app.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, payload: dict):
    payload = dict(payload or {})
    payload["id"] = agent_id
    if not store.get_agent(agent_id):
        raise HTTPException(404, "Агент не найден")
    return store.save_agent(payload)


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str):
    if not store.delete_agent(agent_id):
        raise HTTPException(404, "Агент не найден")
    return {"ok": True}


@app.get("/api/factories")
def list_factories():
    return store.list_factories()


@app.post("/api/factories")
def create_factory(payload: dict):
    ids = payload.get("agent_ids") or []
    if len(ids) < 2:
        raise HTTPException(400, "Выберите минимум двух агентов")
    if not (payload.get("goal") or "").strip():
        raise HTTPException(400, "Нужна цель фабрики")
    return store.save_factory(payload)


@app.put("/api/factories/{factory_id}")
def update_factory(factory_id: str, payload: dict):
    if not store.get_factory(factory_id):
        raise HTTPException(404, "Фабрика не найдена")
    payload = dict(payload or {})
    payload["id"] = factory_id
    return store.save_factory(payload)


@app.delete("/api/factories/{factory_id}")
def delete_factory(factory_id: str):
    if not store.delete_factory(factory_id):
        raise HTTPException(404, "Фабрика не найдена")
    return {"ok": True}


@app.post("/api/factories/{factory_id}/start")
def start_factory(factory_id: str, payload: dict | None = None):
    brief = (payload or {}).get("brief") or ""
    try:
        run = engine.start(factory_id, brief=brief)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return run


@app.get("/api/runs")
def list_runs():
    rows = store.list_runs()
    # лёгкий список без огромных стенограмм
    out = []
    for run in rows:
        out.append(
            {
                "id": run.get("id"),
                "factory_id": run.get("factory_id"),
                "factory_name": run.get("factory_name"),
                "goal": run.get("goal"),
                "status": run.get("status"),
                "round": run.get("round"),
                "max_rounds": run.get("max_rounds"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
            }
        )
    return out


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str):
    if not store.get_run(run_id):
        raise HTTPException(404, "Прогон не найден")

    q: queue.Queue = queue.Queue()

    def listener(kind: str, payload: dict) -> None:
        q.put({"kind": kind, "payload": payload})

    engine.subscribe(run_id, listener)

    def gen():
        # сразу отдаём снимок
        snap = store.get_run(run_id) or {}
        yield f"data: {json.dumps({'kind': 'snapshot', 'payload': snap}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("kind") in ("status",) and (item.get("payload") or {}).get("status") in (
                    "done",
                    "stopped",
                    "error",
                ):
                    # ещё чуть-чуть, вдруг придёт итог
                    continue
        finally:
            engine.unsubscribe(run_id, listener)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/approve")
def approve_run(run_id: str):
    run = engine.approve(run_id)
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.post("/api/runs/{run_id}/pause")
def pause_run(run_id: str):
    run = engine.pause(run_id)
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str):
    run = engine.resume(run_id)
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str):
    run = engine.stop(run_id)
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.post("/api/runs/{run_id}/inject")
def inject_run(run_id: str, payload: dict):
    try:
        run = engine.inject(run_id, (payload or {}).get("text") or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.post("/api/runs/{run_id}/summarize")
def summarize_run(run_id: str):
    run = engine.summarize(run_id)
    if not run:
        raise HTTPException(404, "Прогон не найден")
    return run


@app.post("/api/chat")
def chat(payload: dict):
    history = payload.get("messages") or []
    settings = store.get_settings()
    if payload.get("model"):
        settings = dict(settings)
        settings["model"] = payload["model"]
    messages = chat_system_messages(history)
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            def on_token(delta: str) -> None:
                q.put({"delta": delta})

            text = llm.chat(
                messages,
                settings=settings,
                temperature=float(payload.get("temperature") or 0.7),
                max_tokens=int(payload.get("max_tokens") or 280),
                on_token=on_token,
            )
            q.put({"done": True, "text": text})
        except Exception as exc:
            q.put({"error": str(exc), "done": True})

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            item = q.get()
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("done"):
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    print(f"\n  Фабрика агентов:  http://localhost:{PORT}\n")
    uvicorn.run(app, host=HOST, port=PORT)
