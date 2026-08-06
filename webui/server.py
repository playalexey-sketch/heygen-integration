"""
Web-интерфейс для LTX-2 photo→video агента.

HTML-форма: загрузка фото + голос + текст + настройки видео -> кнопка
"Генерация" -> результат сохраняется в выходную папку на диске.

Запуск:
    python -m webui.server
    # открыть в браузере: http://localhost:8001

Выходная папка по умолчанию: ./ltx2_output
Для Windows можно указать, например:  C:\\ltx2_output
(через переменную окружения LTX2_OUTPUT_DIR или поле в форме).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ltx2.agent import ASPECT_PRESETS, build_talking_video

# ── Выходная папка ────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = os.getenv("LTX2_OUTPUT_DIR", "ltx2_output")

app = FastAPI(title="LTX-2 Photo→Video Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Задачи генерации: id -> dict(статус, прогресс, результат)
_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()

_HTML = Path(__file__).with_name("index.html")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _HTML.read_text(encoding="utf-8")


@app.get("/output/{job_id}")
async def download_output(job_id: str):
    """Скачать готовое видео задачи."""
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
    if not job or not job.get("output_path"):
        return JSONResponse({"error": "Видео ещё не готово"}, status_code=404)
    path = Path(job["output_path"])
    if not path.exists():
        return JSONResponse({"error": "Файл не найден"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return {
        "status": job["status"],
        "stage": job.get("stage", ""),
        "message": job.get("message", ""),
        "output_url": job.get("output_url"),
        "output_path": job.get("output_path"),
        "error": job.get("error"),
        "command": job.get("command"),
        "started_at": job.get("started_at"),
    }


@app.post("/api/generate")
async def generate(
    photo: UploadFile = File(..., description="Фото человека"),
    audio: UploadFile | None = File(default=None, description="Голос/озвучка (mp3/wav)"),
    text: str = Form(default="", description="Текст, который скажет человек на фото"),
    voice_reference: UploadFile | None = File(default=None, description="Образец голоса для клонирования"),
    clone_voice: bool = Form(default=False, description="Клонировать голос из voice_reference"),
    tts_speaker: str = Form(default="aidar", description="Silero голос"),
    language: str = Form(default="ru"),
    duration: int = Form(default=15, description="Длительность видео, сек"),
    fps: float = Form(default=24),
    aspect: str = Form(default="portrait", description="portrait/landscape/square/auto"),
    width: int = Form(default=0, description="0 = авто по aspect"),
    height: int = Form(default=0, description="0 = авто по aspect"),
    image_strength: float = Form(default=0.8),
    seed: int = Form(default=42),
    offload: str = Form(default="none", description="none/cpu/disk"),
    quantization: str = Form(default="", description="fp8-cast / fp8-scaled-mm / пусто"),
    enhance_prompt: bool = Form(default=False),
    output_dir: str = Form(default="", description="Выходная папка (если пусто — папка по умолчанию)"),
) -> dict:
    """Принять файлы и настройки, запустить генерацию в фоне."""
    if photo is None or not photo.filename:
        return JSONResponse({"error": "Загрузите фото"}, status_code=400)
    if not text.strip() and audio is None:
        return JSONResponse({"error": "Загрузите голос (аудио) или введите текст"}, status_code=400)

    job_id = f"job_{int(time.time()*1000)}"
    workdir = _job_workdir(job_id)
    out_dir = _resolve_out_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"talking_avatar_{job_id}.mp4"

    # Сохраняем загруженные файлы в рабочую папку
    photo_path = _save_upload(photo, workdir)
    audio_path = _save_upload(audio, workdir) if audio is not None else None
    voice_ref_path = _save_upload(voice_reference, workdir) if voice_reference is not None else None

    settings = dict(
        photo_path=str(photo_path),
        output_path=str(output_path),
        text=text.strip() or None,
        audio_path=audio_path,
        voice_reference=voice_ref_path,
        clone_voice=clone_voice,
        tts_speaker=tts_speaker,
        language=language,
        duration_seconds=max(1, min(120, duration)),
        fps=fps,
        aspect=aspect,
        width=width or None,
        height=height or None,
        image_strength=image_strength,
        seed=seed,
        enhance_prompt=enhance_prompt,
        quantization=quantization or None,
        offload=offload,
        workdir=str(workdir),
    )

    with _JOB_LOCK:
        _JOBS[job_id] = {
            "status": "queued",
            "stage": "queued",
            "message": "Задача поставлена в очередь…",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    t = threading.Thread(target=_run_job, args=(job_id, settings), daemon=True)
    t.start()

    return {"job_id": job_id, "status": "queued", "output_dir": str(out_dir)}


# ═══════════════════════════════════════════════════════════════
# Внутренние помощники
# ═══════════════════════════════════════════════════════════════

def _run_job(job_id: str, settings: dict) -> None:
    def _set(stage: str, message: str, status: str = "running") -> None:
        with _JOB_LOCK:
            _JOBS[job_id].update(status=status, stage=stage, message=message)

    try:
        _set("voiceover", "Генерирую озвучку…")
        result = build_talking_video(**settings)

        if result.get("dry_run"):
            _set("dry_run", "dry-run", status="dry_run")
            with _JOB_LOCK:
                _JOBS[job_id]["command"] = result["command"]
            return

        if result.get("error"):
            detail = result.get("detail", "")
            message = result["error"] + ("\n" + detail if detail else "")
            _set("failed", message, status="failed")
            with _JOB_LOCK:
                _JOBS[job_id]["error"] = message
                _JOBS[job_id]["detail"] = detail
            return

        _set("done", "Видео готово!", status="completed")
        with _JOB_LOCK:
            _JOBS[job_id]["output_url"] = f"/output/{job_id}"
            _JOBS[job_id]["output_path"] = result["output_path"]

    except Exception as exc:  # noqa: BLE001
        _set("failed", f"Ошибка: {exc}", status="failed")
        with _JOB_LOCK:
            _JOBS[job_id]["error"] = str(exc)


def _job_workdir(job_id: str) -> Path:
    base = Path(os.getenv("LTX2_WORKDIR", "ltx2_work"))
    d = base / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_out_dir(output_dir: str) -> Path:
    if output_dir.strip():
        return Path(output_dir.strip()).expanduser()
    return Path(DEFAULT_OUTPUT_DIR)


def _save_upload(upload: UploadFile, workdir: Path) -> Path | None:
    if upload is None:
        return None
    name = Path(upload.filename or "upload").name
    path = workdir / name
    with open(path, "wb") as f:
        f.write(upload.file.read())
    return path


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    print(f"\n  LTX-2 Photo→Video agent UI:  http://{host}:{port}")
    print(f"  Выходная папка:              {Path(DEFAULT_OUTPUT_DIR).resolve()}\n")
    uvicorn.run(app, host=host, port=port)
