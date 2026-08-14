# -*- coding: utf-8 -*-
"""
HeyGen Студия — постоянное локальное приложение.

Все настройки генерации HeyGen (фото-аватар, видео, голос) вынесены
в веб-форму с русскими названиями полей.

Запуск:  python start.py
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .heygen import HeyGen, HeyGenError
from . import options as OPT

BASE_DIR = Path(__file__).resolve().parent.parent
WORK = BASE_DIR / "work"
OUT = BASE_DIR / "videos"
CFG = BASE_DIR / "settings.json"
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

app = FastAPI(title="HeyGen Студия")

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ───────────────────────────────────────────── настройки
def load_cfg() -> dict:
    if CFG.is_file():
        try:
            return json.loads(CFG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cfg(d: dict) -> None:
    CFG.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def api_key() -> str:
    """Ключ из settings.json имеет приоритет: если пользователь явно сохранил
    (в том числе пустое значение) — используем его, иначе берём из окружения."""
    cfg = load_cfg()
    if "api_key" in cfg:
        return (cfg.get("api_key") or "").strip()
    return os.getenv("HEYGEN_API_KEY", "").strip()


def base_url() -> str:
    return (load_cfg().get("base_url")
            or os.getenv("HEYGEN_BASE_URL", "https://api.heygen.com")).strip()


def client() -> HeyGen:
    return HeyGen(api_key=api_key(), base_url=base_url())


# ───────────────────────────────────────────── утилиты задач
def jset(jid: str, **kw) -> None:
    with _LOCK:
        _JOBS.setdefault(jid, {}).update(kw)


def jlog(jid: str, msg: str) -> None:
    with _LOCK:
        _JOBS.setdefault(jid, {}).setdefault("log", []).append(msg)
    print(f"[{jid[:8]}] {msg}", flush=True)


def save_upload(up: UploadFile, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    raw = os.path.basename(up.filename or "file")
    safe = "".join(c for c in raw if c.isalnum() or c in "._- ") or "file"
    path = folder / safe
    with path.open("wb") as f:
        shutil.copyfileobj(up.file, f)
    return str(path)


def num(v, default, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


# ───────────────────────────────────────────── страницы
@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE_DIR / "app" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/options")
async def get_options():
    """Все справочники для формы — рисуются из одного источника."""
    return {
        "engines": OPT.ENGINES,
        "aspect_ratios": OPT.ASPECT_RATIOS,
        "resolutions": OPT.RESOLUTIONS,
        "output_formats": OPT.OUTPUT_FORMATS,
        "expressiveness": OPT.EXPRESSIVENESS,
        "caption_formats": OPT.CAPTION_FORMATS,
        "caption_styles": OPT.CAPTION_STYLES,
        "watermark_positions": OPT.WATERMARK_POSITIONS,
        "background_types": OPT.BACKGROUND_TYPES,
        "avatar_age": OPT.AVATAR_AGE,
        "avatar_gender": OPT.AVATAR_GENDER,
        "avatar_ethnicity": OPT.AVATAR_ETHNICITY,
        "avatar_style": OPT.AVATAR_STYLE,
        "avatar_orientation": OPT.AVATAR_ORIENTATION,
        "avatar_pose": OPT.AVATAR_POSE,
        "voice_emotions": OPT.VOICE_EMOTIONS,
        "voice_locales": OPT.VOICE_LOCALES,
        "voice_ranges": OPT.VOICE_RANGES,
    }


@app.get("/api/settings")
async def get_settings():
    cfg = load_cfg()
    key = cfg.get("api_key") or os.getenv("HEYGEN_API_KEY", "")
    return {
        "has_key": bool(key),
        "key_masked": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("•" * len(key)),
        "base_url": base_url(),
        "is_test_mode": "127.0.0.1" in base_url() or "localhost" in base_url(),
        "saved_voices": cfg.get("saved_voices", []),
        "presets": cfg.get("presets", {}),
    }


@app.post("/api/settings")
async def set_settings(request: Request):
    body = await request.json()
    cfg = load_cfg()
    if "api_key" in body:
        cfg["api_key"] = (body.get("api_key") or "").strip()
    if "base_url" in body:
        cfg["base_url"] = (body.get("base_url") or "").strip() or "https://api.heygen.com"
    save_cfg(cfg)
    return {"ok": True}


@app.post("/api/check")
async def check_connection():
    """Проверка связи с API и ключа."""
    if not api_key():
        return JSONResponse({"ok": False, "error": "Ключ не задан."}, status_code=400)
    try:
        c = client()
        voices = c.list_voices()
        avatars = c.list_avatars()
        w = c.wallet()
        return {"ok": True, "voices": len(voices), "avatars": len(avatars),
                "base_url": base_url(), "wallet": w}
    except HeyGenError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/api/avatars")
async def avatars():
    try:
        return {"items": client().list_avatars()}
    except HeyGenError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/voices")
async def voices():
    try:
        return {"items": client().list_voices()}
    except HeyGenError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/save-voice")
async def save_voice(request: Request):
    """Сохранить ID клонированного голоса для повторного использования."""
    body = await request.json()
    cfg = load_cfg()
    lst = cfg.setdefault("saved_voices", [])
    vid, name = body.get("voice_id"), body.get("name") or "Мой голос"
    if vid and not any(x.get("voice_id") == vid for x in lst):
        lst.append({"voice_id": vid, "name": name})
        save_cfg(cfg)
    return {"ok": True, "saved_voices": lst}


# ───────────────────────────────────────────── генерация внешности
def _run_photo_gen(jid: str, p: dict):
    try:
        jset(jid, status="running", progress=10, stage="Отправляю описание внешности")
        c = client()
        gid = c.generate_avatar_photos(
            name=p["name"], age=p["age"], gender=p["gender"],
            ethnicity=p["ethnicity"], orientation=p["orientation"],
            pose=p["pose"], style=p["style"], appearance=p["appearance"])
        jlog(jid, f"Генерация запущена: {gid}")
        jset(jid, progress=35, stage="Рисую варианты внешности")
        end = time.time() + 420
        while time.time() < end:
            time.sleep(4)
            d = c.get_generation(gid)
            st = d.get("status", "")
            if st in ("success", "completed"):
                urls = d.get("image_url_list") or []
                keys = d.get("image_key_list") or []
                jset(jid, status="done", progress=100, stage="Готово",
                     images=urls, image_keys=keys)
                jlog(jid, f"Получено вариантов: {len(urls)}")
                return
            if st in ("failed", "error"):
                raise HeyGenError("Не удалось сгенерировать внешность.")
            jset(jid, progress=min(90, (_JOBS[jid].get("progress") or 35) + 4))
        raise HeyGenError("Превышено время ожидания генерации внешности.")
    except Exception as e:
        jlog(jid, f"ОШИБКА: {e}")
        jset(jid, status="error", error=str(e), stage="Ошибка")


@app.post("/api/generate-appearance")
async def generate_appearance(
    name: str = Form("Мой аватар"),
    age: str = Form("Young Adult"),
    gender: str = Form("Unspecified"),
    ethnicity: str = Form("Unspecified"),
    orientation: str = Form("vertical"),
    pose: str = Form("half_body"),
    style: str = Form("Realistic"),
    appearance: str = Form(""),
):
    if not api_key():
        return JSONResponse({"error": "Сначала укажите ключ API в настройках."},
                            status_code=400)
    if not appearance.strip():
        return JSONResponse({"error": "Опишите внешность аватара."}, status_code=400)
    jid = uuid.uuid4().hex
    _JOBS[jid] = {"status": "queued", "progress": 0, "stage": "В очереди", "log": []}
    threading.Thread(target=_run_photo_gen, args=(jid, dict(
        name=name, age=age, gender=gender, ethnicity=ethnicity,
        orientation=orientation, pose=pose, style=style,
        appearance=appearance.strip())), daemon=True).start()
    return {"job_id": jid}


# ───────────────────────────────────────────── генерация видео
def _run_video(jid: str, p: dict):
    try:
        jset(jid, status="running", progress=4, stage="Подключаюсь к HeyGen")
        c = client()

        # ── 1. Аватар ────────────────────────────────────────
        avatar_id = p.get("avatar_id") or ""
        if p["avatar_mode"] == "photo":
            photos = p.get("photos") or []
            if not photos:
                raise HeyGenError("Не загружено фото для аватара.")
            jset(jid, progress=10, stage="Загружаю фото")
            asset = c.upload_asset(photos[0])
            jlog(jid, f"Фото загружено: {os.path.basename(photos[0])}")
            if len(photos) > 1:
                jlog(jid, f"Ещё {len(photos)-1} фото сохранено как запасные ракурсы")
            jset(jid, progress=18, stage="Создаю аватар из фото")
            res = c.create_avatar_from_photo(p.get("avatar_name") or "Аватар", asset)
            avatar_id = res["avatar_id"]
            jlog(jid, f"Аватар создан: {avatar_id}")
            jset(jid, progress=26, stage="Жду готовности аватара")
            c.wait_avatar(avatar_id, on_tick=lambda s: jset(jid, stage=f"Аватар: {s}"))
        elif p["avatar_mode"] == "prompt":
            jset(jid, progress=14, stage="Создаю аватар по описанию")
            res = c.create_avatar_from_prompt(
                p.get("avatar_name") or "Аватар", p.get("appearance_prompt") or "")
            avatar_id = res["avatar_id"]
            jlog(jid, f"Аватар по описанию создан: {avatar_id}")
            jset(jid, progress=26, stage="Жду готовности аватара")
            c.wait_avatar(avatar_id, on_tick=lambda s: jset(jid, stage=f"Аватар: {s}"))
        else:
            jlog(jid, f"Использую готовый аватар: {avatar_id}")

        if not avatar_id:
            raise HeyGenError("Не определён аватар для видео.")

        # ── 2. Голос ─────────────────────────────────────────
        voice_id = ""
        audio_asset_id = None
        audio_url = None
        vm = p["voice_mode"]

        if vm == "audio":
            jset(jid, progress=38, stage="Загружаю вашу озвучку")
            audio_asset_id = c.upload_asset(p["audio_path"])
            jlog(jid, "Режим голоса: своя аудиодорожка")
        elif vm == "audio_url":
            audio_url = p["audio_url"]
            jlog(jid, "Режим голоса: озвучка по ссылке")
        elif vm == "clone":
            jset(jid, progress=34, stage="Загружаю образец голоса")
            a = c.upload_asset(p["voice_sample"])
            jset(jid, progress=42, stage="Клонирую голос")
            cid = c.clone_voice(p.get("voice_name") or "Мой голос", a)
            voice_id = c.wait_voice_clone(
                cid, on_tick=lambda s: jset(jid, stage=f"Клонирование: {s}"))
            jset(jid, cloned_voice_id=voice_id)
            jlog(jid, f"Голос клонирован: {voice_id}")
        else:  # library / cloned_id
            voice_id = p.get("voice_id_input") or ""
            jlog(jid, f"Голос: {voice_id or 'по умолчанию у аватара'}")

        # ── 3. Сборка запроса ────────────────────────────────
        payload: dict = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "aspect_ratio": p["aspect_ratio"],
            "resolution": p["resolution"],
            "output_format": p["output_format"],
        }
        if p.get("title"):
            payload["title"] = p["title"]
        if p.get("engine"):
            payload["engine"] = {"type": p["engine"]}
        if p.get("motion_prompt"):
            payload["motion_prompt"] = p["motion_prompt"]
        if p.get("engine") == "avatar_iv" and p.get("expressiveness"):
            payload["expressiveness"] = p["expressiveness"]

        # аудио источник
        if audio_asset_id:
            payload["audio_asset_id"] = audio_asset_id
        elif audio_url:
            payload["audio_url"] = audio_url
        else:
            payload["script"] = p["script"]
            if voice_id:
                payload["voice_id"] = voice_id
            vs: dict = {
                "speed": p["voice_speed"],
                "pitch": p["voice_pitch"],
                "volume": p["voice_volume"],
            }
            if p.get("voice_locale"):
                vs["locale"] = p["voice_locale"]
            es = {}
            if p.get("voice_emotion"):
                es["style"] = p["voice_emotion"]
            if p.get("use_engine_settings"):
                es.update({
                    "similarity_boost": p["similarity_boost"],
                    "stability": p["stability"],
                    "use_speaker_boost": p["speaker_boost"],
                })
            if es:
                vs["engine_settings"] = es
            payload["voice_settings"] = vs

        # фон
        bt = p.get("background_type")
        if bt == "remove":
            payload["remove_background"] = True
        elif bt == "color" and p.get("background_color"):
            payload["background"] = {"value": p["background_color"]}
        elif bt == "image_url" and p.get("background_url"):
            payload["background"] = {"url": p["background_url"]}
        elif bt == "image_file" and p.get("background_file"):
            jset(jid, progress=48, stage="Загружаю фон")
            payload["background"] = {"asset_id": c.upload_asset(p["background_file"])}

        # субтитры
        if p.get("caption_format"):
            cap = {"file_format": p["caption_format"]}
            if p.get("caption_style"):
                cap["style"] = p["caption_style"]
            payload["caption"] = cap

        # водяной знак
        if p.get("watermark_url"):
            payload["watermark"] = {
                "image": {"type": "url", "url": p["watermark_url"]},
                "scale": p["watermark_scale"],
                "opacity": p["watermark_opacity"],
                "placement": {"position": p["watermark_position"],
                              "offset_x": int(p["watermark_x"]),
                              "offset_y": int(p["watermark_y"])},
            }

        if p.get("callback_url"):
            payload["callback_url"] = p["callback_url"]
        if p.get("brand_glossary_id"):
            payload["brand_glossary_id"] = p["brand_glossary_id"]

        jset(jid, progress=55, stage="Отправляю задачу на рендер",
             request_payload=payload)
        jlog(jid, "Параметры: " + json.dumps(
            {k: v for k, v in payload.items() if k != "script"}, ensure_ascii=False))

        vid = c.create_video(payload)
        jset(jid, video_id=vid, progress=62, stage="Рендер видео (2–10 минут)")
        jlog(jid, f"Идентификатор видео: {vid}")

        # ── 4. Ожидание ──────────────────────────────────────
        end = time.time() + int(p.get("timeout", 1800))
        info = {}
        while time.time() < end:
            time.sleep(6)
            info = c.get_video(vid)
            st = info.get("status", "")
            pr = info.get("progress")
            if pr is not None:
                jset(jid, progress=min(62 + int(float(pr) * 0.33), 96))
            if st in ("completed", "success") and info.get("video_url"):
                break
            if st in ("failed", "error"):
                raise HeyGenError(f"Рендер не удался: {info.get('error') or st}")
        else:
            raise HeyGenError("Превышено время ожидания рендера.")

        # ── 5. Скачивание ────────────────────────────────────
        jset(jid, progress=97, stage="Скачиваю готовый файл")
        ext = "webm" if p["output_format"] == "webm" else "mp4"
        fname = f"{jid[:8]}_video.{ext}"
        fpath = OUT / fname
        r = requests.get(info["video_url"], timeout=900, stream=True)
        r.raise_for_status()
        with fpath.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)

        sub_name = None
        if info.get("subtitle_url"):
            try:
                sr = requests.get(info["subtitle_url"], timeout=120)
                if sr.ok:
                    sub_name = f"{jid[:8]}_subtitles.{p.get('caption_format') or 'srt'}"
                    (OUT / sub_name).write_bytes(sr.content)
            except Exception:
                pass

        jset(jid, status="done", progress=100, stage="Готово",
             download=f"/api/file/{fname}",
             subtitles=f"/api/file/{sub_name}" if sub_name else None,
             remote_url=info.get("video_url"),
             duration=info.get("duration"),
             size_mb=round(fpath.stat().st_size / 1048576, 2))
        jlog(jid, f"Сохранено: {fpath.name}")

    except HeyGenError as e:
        jlog(jid, f"ОШИБКА: {e}")
        jset(jid, status="error", error=str(e), stage="Ошибка")
    except Exception as e:
        jlog(jid, f"ОШИБКА: {e}")
        traceback.print_exc()
        jset(jid, status="error", error=str(e), stage="Ошибка")


@app.post("/api/generate")
async def generate(
    avatar_mode: str = Form("photo"),
    avatar_id: str = Form(""),
    avatar_name: str = Form(""),
    appearance_prompt: str = Form(""),
    photos: list[UploadFile] = File(default=[]),
    voice_mode: str = Form("library"),
    voice_id_input: str = Form(""),
    voice_name: str = Form("Мой голос"),
    voice_sample: Optional[UploadFile] = File(default=None),
    audio: Optional[UploadFile] = File(default=None),
    audio_url: str = Form(""),
    script: str = Form(""),
    motion_prompt: str = Form(""),
    engine: str = Form("avatar_iv"),
    expressiveness: str = Form("low"),
    aspect_ratio: str = Form("9:16"),
    resolution: str = Form("1080p"),
    output_format: str = Form("mp4"),
    title: str = Form(""),
    voice_speed: str = Form("1.0"),
    voice_pitch: str = Form("0"),
    voice_volume: str = Form("1.0"),
    voice_locale: str = Form(""),
    voice_emotion: str = Form(""),
    use_engine_settings: str = Form("false"),
    similarity_boost: str = Form("0.5"),
    stability: str = Form("0.5"),
    speaker_boost: str = Form("true"),
    background_type: str = Form("none"),
    background_color: str = Form(""),
    background_url: str = Form(""),
    background_file: Optional[UploadFile] = File(default=None),
    caption_format: str = Form(""),
    caption_style: str = Form(""),
    watermark_url: str = Form(""),
    watermark_scale: str = Form("1"),
    watermark_opacity: str = Form("1"),
    watermark_position: str = Form("bottom_right"),
    watermark_x: str = Form("0"),
    watermark_y: str = Form("0"),
    callback_url: str = Form(""),
    brand_glossary_id: str = Form(""),
):
    if not api_key():
        return JSONResponse(
            {"error": "Не указан ключ API. Откройте «Настройки подключения» вверху."},
            status_code=400)

    jid = uuid.uuid4().hex
    jdir = WORK / jid

    photo_paths = [save_upload(u, jdir / "photos")
                   for u in (photos or []) if u and u.filename]
    audio_path = save_upload(audio, jdir / "audio") if audio and audio.filename else None
    sample_path = (save_upload(voice_sample, jdir / "voice")
                   if voice_sample and voice_sample.filename else None)
    bg_path = (save_upload(background_file, jdir / "bg")
               if background_file and background_file.filename else None)

    # ── валидация ────────────────────────────────────────
    if avatar_mode == "photo" and not photo_paths:
        return JSONResponse({"error": "Загрузите хотя бы одно фото."}, status_code=400)
    if avatar_mode == "existing" and not avatar_id:
        return JSONResponse({"error": "Выберите готовый аватар."}, status_code=400)
    if avatar_mode == "prompt" and not appearance_prompt.strip():
        return JSONResponse({"error": "Опишите внешность аватара."}, status_code=400)

    if voice_mode == "audio" and not audio_path:
        return JSONResponse({"error": "Загрузите файл озвучки."}, status_code=400)
    if voice_mode == "audio_url" and not audio_url.strip():
        return JSONResponse({"error": "Укажите ссылку на аудиофайл."}, status_code=400)
    if voice_mode == "clone" and not sample_path:
        return JSONResponse({"error": "Загрузите образец голоса для клонирования."},
                            status_code=400)
    if voice_mode in ("library", "clone", "cloned_id") and not script.strip():
        return JSONResponse({"error": "Впишите текст, который произнесёт аватар."},
                            status_code=400)
    if voice_mode == "library" and not voice_id_input:
        return JSONResponse({"error": "Выберите голос из библиотеки."}, status_code=400)
    if voice_mode == "cloned_id" and not voice_id_input.strip():
        return JSONResponse({"error": "Укажите ID ранее клонированного голоса."},
                            status_code=400)
    if len(script) > 5000:
        return JSONResponse({"error": "Текст длиннее 5000 символов — сократите."},
                            status_code=400)

    if aspect_ratio not in OPT.valid_values(OPT.ASPECT_RATIOS):
        return JSONResponse({"error": "Недопустимое соотношение сторон."}, status_code=400)
    if resolution not in OPT.valid_values(OPT.RESOLUTIONS):
        return JSONResponse({"error": "Недопустимое разрешение."}, status_code=400)

    p = dict(
        avatar_mode=avatar_mode, avatar_id=avatar_id.strip(),
        avatar_name=avatar_name.strip(), appearance_prompt=appearance_prompt.strip(),
        photos=photo_paths,
        voice_mode=voice_mode, voice_id_input=voice_id_input.strip(),
        voice_name=voice_name.strip(), voice_sample=sample_path,
        audio_path=audio_path, audio_url=audio_url.strip(),
        script=script.strip(), motion_prompt=motion_prompt.strip(),
        engine=engine, expressiveness=expressiveness,
        aspect_ratio=aspect_ratio, resolution=resolution,
        output_format=output_format, title=title.strip(),
        voice_speed=num(voice_speed, 1.0, 0.5, 1.5),
        voice_pitch=int(num(voice_pitch, 0, -50, 50)),
        voice_volume=num(voice_volume, 1.0, 0.0, 1.0),
        voice_locale=voice_locale.strip(), voice_emotion=voice_emotion.strip(),
        use_engine_settings=(use_engine_settings == "true"),
        similarity_boost=num(similarity_boost, 0.5, 0, 1),
        stability=num(stability, 0.5, 0, 1),
        speaker_boost=(speaker_boost == "true"),
        background_type=background_type, background_color=background_color.strip(),
        background_url=background_url.strip(), background_file=bg_path,
        caption_format=caption_format, caption_style=caption_style,
        watermark_url=watermark_url.strip(),
        watermark_scale=num(watermark_scale, 1, 0, 5),
        watermark_opacity=num(watermark_opacity, 1, 0, 1),
        watermark_position=watermark_position,
        watermark_x=num(watermark_x, 0), watermark_y=num(watermark_y, 0),
        callback_url=callback_url.strip(), brand_glossary_id=brand_glossary_id.strip(),
    )

    _JOBS[jid] = {"status": "queued", "progress": 0, "stage": "В очереди", "log": []}
    threading.Thread(target=_run_video, args=(jid, p), daemon=True).start()
    return {"job_id": jid}


@app.get("/api/job/{jid}")
async def job(jid: str):
    j = _JOBS.get(jid)
    if not j:
        return JSONResponse({"error": "Задача не найдена"}, status_code=404)
    return j


@app.get("/api/file/{name}")
async def get_file(name: str):
    p = OUT / os.path.basename(name)
    if not p.is_file():
        return JSONResponse({"error": "Файл не найден"}, status_code=404)
    return FileResponse(p, filename=p.name)


@app.get("/api/history")
async def history():
    items = []
    for f in sorted(OUT.glob("*.*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix in (".mp4", ".webm"):
            items.append({"name": f.name, "url": f"/api/file/{f.name}",
                          "size_mb": round(f.stat().st_size / 1048576, 2),
                          "time": time.strftime("%d.%m.%Y %H:%M",
                                                time.localtime(f.stat().st_mtime))})
    return {"items": items[:50]}
