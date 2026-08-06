"""
Локальный веб-чат с моделью Hermes (Nous Research) через Ollama.

Работает отдельно от агента: Ollama запускает Hermes на вашем ПК, а этот
сервер даёт простой бесплатный веб-интерфейс.

Запуск:
    python run_hermes.py          (или run_hermes.bat)
    открыть в браузере: http://localhost:8002

Требуется установленный Ollama (см. install_hermes.bat):
    https://ollama.com
    ollama pull hermes3:8b
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

# Порт Ollama по умолчанию
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# Модели Hermes, доступные локально
HERMES_MODELS = [
    "hermes3:3b",   # самая лёгкая (~2.6 ГБ) — для слабых ПК
    "hermes3:8b",   # по умолчанию (~4.7 ГБ) — оптимально
    "hermes3:70b",  # большая (~40 ГБ) — нужен GPU/много ОЗУ
    "hermes3:405b", # флагман — нужен мощный GPU
]

app = FastAPI(title="Hermes Local Chat", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_HTML = Path(__file__).with_name("chat.html")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _HTML.read_text(encoding="utf-8")


@app.get("/api/models")
async def list_models() -> dict:
    """Список моделей Hermes (предустановленные) + доступность Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        installed = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        installed = []
    return {
        "models": HERMES_MODELS,
        "installed": installed,
        "ollama_up": bool(installed) or _ollama_alive(),
    }


def _ollama_alive() -> bool:
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except Exception:  # noqa: BLE001
        return False


@app.post("/api/chat")
async def chat(req: dict) -> StreamingResponse:
    """Прокси-чат к Ollama со стримингом (SSE)."""
    model = req.get("model", "hermes3:8b")
    messages = req.get("messages", [])

    payload = {"model": model, "messages": messages, "stream": True}

    def gen():
        try:
            with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=120) as resp:
                if resp.status_code != 200:
                    body = resp.text[:500]
                    yield f'data: {json.dumps({"error": f"Ollama: {resp.status_code} {body}"})}\n\n'
                    return
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield f'data: {json.dumps({"delta": content})}\n\n'
                    if chunk.get("done"):
                        yield f'data: {json.dumps({"done": True})}\n\n'
        except Exception as exc:  # noqa: BLE001
            yield f'data: {json.dumps({"error": f"Нет связи с Ollama: {exc}"})}\n\n'

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8002"))
    print(f"\n  Hermes Local Chat:  http://localhost:{port}")
    print(f"  Ollama:            {OLLAMA_URL}\n")
    uvicorn.run(app, host=host, port=port)
