# -*- coding: utf-8 -*-
"""
Аватар-Студия — интерактивная форма создания видео цифрового аватара.

Возможности:
  • загрузка нескольких фото (одно основное + запасные ракурсы)
  • детальный сценарий (motion prompt) и опциональный текст речи
  • голос: своё аудио / клонирование своего голоса / готовый цифровой аватар
    и голос из библиотеки HeyGen
  • фоновая генерация с прогрессом и скачиванием готового видео по ссылке

Запуск:
    python -m studio.server
    открыть http://localhost:8010
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent / "studio_work"
OUTPUT = ROOT.parent / "studio_output"
WORK.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

app = FastAPI(title="Аватар-Студия", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ────────────────────────────────────────────── helpers
def _set(job_id: str, **kw) -> None:
    with _LOCK:
        _JOBS.setdefault(job_id, {}).update(kw)


def _log(job_id: str, msg: str) -> None:
    with _LOCK:
        job = _JOBS.setdefault(job_id, {})
        job.setdefault("log", []).append(msg)
    print(f"[{job_id[:8]}] {msg}", flush=True)


def _save_upload(up: UploadFile, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = os.path.basename(up.filename or "file")
    safe = "".join(c for c in name if c.isalnum() or c in "._- ") or "file"
    path = dest_dir / safe
    with path.open("wb") as f:
        shutil.copyfileobj(up.file, f)
    return path


def _has_key() -> bool:
    return bool(os.getenv("HEYGEN_API_KEY"))


# ────────────────────────────────────────────── pages
@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (ROOT / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def api_status() -> dict:
    return {"has_key": _has_key()}


@app.get("/api/avatars")
async def api_avatars() -> JSONResponse:
    """Список готовых цифровых аватаров аккаунта."""
    if not _has_key():
        return JSONResponse({"error": "Нет ключа HEYGEN_API_KEY"}, status_code=400)
    try:
        from heygen_client import HeyGenClient
        items = HeyGenClient().list_avatars()
        return JSONResponse({"items": [
            {"id": a.avatar_id, "name": a.avatar_name or a.avatar_id,
             "preview": a.preview_image_url, "gender": a.gender}
            for a in items
        ]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/voices")
async def api_voices(lang: str = "") -> JSONResponse:
    """Список голосов библиотеки (можно фильтровать по языку)."""
    if not _has_key():
        return JSONResponse({"error": "Нет ключа HEYGEN_API_KEY"}, status_code=400)
    try:
        from heygen_client import HeyGenClient
        items = HeyGenClient().list_voices()
        out = []
        for v in items:
            if lang and lang.lower() not in (v.language or "").lower():
                continue
            out.append({"id": v.voice_id, "name": v.voice_name or v.voice_id,
                        "language": v.language, "gender": v.gender,
                        "preview": v.preview_audio_url})
        out.sort(key=lambda x: (x["language"], x["name"]))
        return JSONResponse({"items": out})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# ────────────────────────────────────────────── generation
def _run_job(job_id: str, params: dict) -> None:
    """Фоновая генерация видео."""
    try:
        _set(job_id, status="running", progress=5, stage="Подготовка материалов")
        _log(job_id, "Старт задачи")

        source = params["source"]
        photos: list[str] = params["photos"]
        script: Optional[str] = params.get("script") or None
        scenario: Optional[str] = params.get("scenario") or None
        audio_path: Optional[str] = params.get("audio_path")
        voice_sample: Optional[str] = params.get("voice_sample")
        voice_id: Optional[str] = params.get("voice_id") or None
        avatar_id: Optional[str] = params.get("avatar_id") or None

        from heygen_client import HeyGenClient, HeyGenError
        client = HeyGenClient()

        # ── 1. Аватар ────────────────────────────────────────
        if source == "avatar":
            if not avatar_id:
                raise ValueError("Не выбран цифровой аватар.")
            _set(job_id, progress=20, stage="Использую готовый аватар")
            _log(job_id, f"Аватар из библиотеки: {avatar_id}")
            final_avatar_id = avatar_id
        else:
            if not photos:
                raise ValueError("Не загружено ни одного фото.")
            _set(job_id, progress=12, stage="Загружаю фото")
            main_photo = photos[0]
            _log(job_id, f"Основное фото: {os.path.basename(main_photo)}")
            if len(photos) > 1:
                _log(job_id, f"Запасные ракурсы ({len(photos)-1}) сохранены — "
                             f"их можно использовать при повторной попытке")

            asset = client.upload_asset(main_photo)
            _set(job_id, progress=22, stage="Создаю фото-аватар")
            avatar = client.create_photo_avatar(
                name=params.get("avatar_name") or "Аватар из студии",
                image_asset_id=asset.asset_id,
            )
            if not avatar.avatar_id:
                raise ValueError(f"Не удалось создать аватар: {avatar.error or 'ошибка'}")
            _log(job_id, f"Аватар создан: {avatar.avatar_id}")

            _set(job_id, progress=32, stage="Жду готовности аватара")
            try:
                st = client.poll_photo_avatar(avatar.avatar_id)
                if st.status != "completed":
                    raise ValueError(
                        f"Аватар не готов: {st.error or st.status}. "
                        f"Попробуй другое фото — анфас, лицо крупно, ровный свет.")
            except HeyGenError as e:
                _log(job_id, f"Предупреждение при ожидании аватара: {e}")
            final_avatar_id = avatar.avatar_id

        # ── 2. Голос ─────────────────────────────────────────
        audio_asset_id = None
        final_voice_id = voice_id

        if audio_path:
            _set(job_id, progress=45, stage="Загружаю твою озвучку")
            a = client.upload_asset(audio_path)
            audio_asset_id = a.asset_id
            _log(job_id, "Режим: липсинк загруженного аудио")
        elif voice_sample:
            _set(job_id, progress=42, stage="Клонирую твой голос")
            a = client.upload_asset(voice_sample)
            clone = client.clone_voice(
                voice_name=params.get("voice_name") or "Мой голос",
                audio_asset_id=a.asset_id,
            )
            _set(job_id, progress=55, stage="Жду готовности клона голоса")
            st = client.poll_voice_clone(clone.voice_clone_id)
            if st.status != "completed" or not st.voice_id:
                raise ValueError(f"Клонирование не удалось: {st.error or st.status}")
            final_voice_id = st.voice_id
            _set(job_id, cloned_voice_id=st.voice_id)
            _log(job_id, f"Голос клонирован: {st.voice_id}")
        else:
            _log(job_id, "Режим: голос из библиотеки")

        if not audio_asset_id and not script:
            raise ValueError("Нужен текст речи или загруженная озвучка.")

        # ── 3. Видео ─────────────────────────────────────────
        _set(job_id, progress=62, stage="Отправляю задачу на рендер")
        video = client.create_photo_video(
            avatar_id=final_avatar_id,
            voice_id=final_voice_id,
            script=None if audio_asset_id else script,
            audio_asset_id=audio_asset_id,
            title=params.get("title") or "Видео из Аватар-Студии",
            aspect_ratio=params.get("aspect_ratio", "9:16"),
            resolution=params.get("resolution", "1080p"),
            background=params.get("background") or None,
            motion_prompt=scenario,
        )
        if not video.video_id:
            raise ValueError("HeyGen не вернул video_id.")
        _set(job_id, video_id=video.video_id, progress=70,
             stage="Рендер видео (2–10 минут)")
        _log(job_id, f"video_id: {video.video_id}")

        # ── 4. Ожидание ──────────────────────────────────────
        deadline = time.time() + int(params.get("timeout", 1800))
        url = None
        while time.time() < deadline:
            time.sleep(10)
            st = client.get_video(video.video_id)
            if st.progress:
                _set(job_id, progress=min(70 + int(st.progress * 0.25), 95))
            if st.status == "completed" and st.video_url:
                url = st.video_url
                break
            if st.status == "failed":
                raise ValueError(f"Рендер не удался: {st.error or 'неизвестная ошибка'}")
        if not url:
            raise TimeoutError("Превышено время ожидания рендера.")

        # ── 5. Скачивание ────────────────────────────────────
        _set(job_id, progress=96, stage="Скачиваю готовое видео")
        out_name = f"{job_id[:8]}_avatar.mp4"
        out_path = OUTPUT / out_name
        r = requests.get(url, timeout=600, stream=True)
        r.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)

        _set(job_id, status="done", progress=100, stage="Готово",
             download=f"/api/download/{out_name}",
             remote_url=url, file=str(out_path),
             size_mb=round(out_path.stat().st_size / 1048576, 1))
        _log(job_id, f"Готово: {out_path}")

    except requests.exceptions.RequestException as e:
        msg = ("Нет связи с api.heygen.com. Проверь интернет, доступность сервиса "
               f"и корректность ключа. Техническая деталь: {e}")
        _log(job_id, f"ОШИБКА СЕТИ: {e}")
        _set(job_id, status="error", error=msg, stage="Ошибка сети")
    except Exception as e:
        text = str(e)
        if "401" in text or "403" in text or "unauthorized" in text.lower():
            text = "Ключ HEYGEN_API_KEY отклонён. Проверь, что он верный и активен."
        elif "402" in text or "credit" in text.lower() or "quota" in text.lower():
            text = "Недостаточно кредитов HeyGen на аккаунте."
        _log(job_id, f"ОШИБКА: {e}")
        traceback.print_exc()
        _set(job_id, status="error", error=text, stage="Ошибка")


@app.post("/api/generate")
async def api_generate(
    source: str = Form("photo"),
    photos: list[UploadFile] = File(default=[]),
    audio: Optional[UploadFile] = File(default=None),
    voice_sample: Optional[UploadFile] = File(default=None),
    avatar_id: str = Form(""),
    voice_id: str = Form(""),
    script: str = Form(""),
    scenario: str = Form(""),
    title: str = Form(""),
    avatar_name: str = Form(""),
    voice_name: str = Form(""),
    aspect_ratio: str = Form("9:16"),
    resolution: str = Form("1080p"),
    background: str = Form(""),
) -> JSONResponse:
    if not _has_key():
        return JSONResponse(
            {"error": "Не задан HEYGEN_API_KEY. Создай файл .env с ключом и перезапусти."},
            status_code=400)

    job_id = uuid.uuid4().hex
    jdir = WORK / job_id
    jdir.mkdir(parents=True, exist_ok=True)

    photo_paths = []
    for up in photos or []:
        if up and up.filename:
            photo_paths.append(str(_save_upload(up, jdir / "photos")))

    audio_path = None
    if audio and audio.filename:
        audio_path = str(_save_upload(audio, jdir / "audio"))
    sample_path = None
    if voice_sample and voice_sample.filename:
        sample_path = str(_save_upload(voice_sample, jdir / "voice"))

    # валидация
    if source == "photo" and not photo_paths:
        return JSONResponse({"error": "Загрузи хотя бы одно фото."}, status_code=400)
    if source == "avatar" and not avatar_id:
        return JSONResponse({"error": "Выбери цифрового аватара."}, status_code=400)
    if not audio_path and not script.strip():
        return JSONResponse(
            {"error": "Нужен текст речи или загруженная озвучка."}, status_code=400)
    if script.strip() and not audio_path and not sample_path and not voice_id:
        return JSONResponse(
            {"error": "Для текста выбери голос: загрузи образец для клонирования "
                      "или выбери голос из библиотеки."}, status_code=400)

    params = dict(source=source, photos=photo_paths, audio_path=audio_path,
                  voice_sample=sample_path, avatar_id=avatar_id, voice_id=voice_id,
                  script=script.strip(), scenario=scenario.strip(), title=title,
                  avatar_name=avatar_name, voice_name=voice_name,
                  aspect_ratio=aspect_ratio, resolution=resolution,
                  background=background.strip())

    _JOBS[job_id] = {"status": "queued", "progress": 0,
                     "stage": "В очереди", "log": []}
    threading.Thread(target=_run_job, args=(job_id, params), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.get("/api/job/{job_id}")
async def api_job(job_id: str) -> JSONResponse:
    job = _JOBS.get(job_id)
    if not job:
        return JSONResponse({"error": "Задача не найдена"}, status_code=404)
    return JSONResponse(job)


@app.get("/api/download/{name}")
async def api_download(name: str):
    path = OUTPUT / os.path.basename(name)
    if not path.is_file():
        return JSONResponse({"error": "Файл не найден"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("STUDIO_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)
