# -*- coding: utf-8 -*-
"""
Тестовый (mock) сервер HeyGen API.

Полностью имитирует поведение api.heygen.com: те же пути, те же формы ответов,
асинхронные статусы с задержками. Нужен, чтобы проверить всю механику
приложения и формы, не тратя реальные кредиты и без настоящего ключа.

Запуск:
    python -m mock.mock_heygen        # слушает :8765
Использование в приложении:
    HEYGEN_BASE_URL=http://127.0.0.1:8765
    HEYGEN_API_KEY=test_key
"""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Mock HeyGen API")

_VIDEOS: dict[str, dict] = {}
_AVATARS: dict[str, dict] = {}
_CLONES: dict[str, dict] = {}
_GENPHOTOS: dict[str, dict] = {}

# Длительность имитации этапов (сек)
AVATAR_READY_AFTER = 4
CLONE_READY_AFTER = 4
VIDEO_READY_AFTER = 12
PHOTO_READY_AFTER = 5

# 1x1 mp4-заглушка не нужна — отдаём валидный маленький файл
_SAMPLE_MP4 = Path(__file__).with_name("sample.mp4")

_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _auth_ok(request: Request) -> bool:
    key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    return bool(key)


def _deny():
    return JSONResponse({"error": {"message": "Unauthorized: missing API key"}},
                        status_code=401)


# ─────────────────────────────────────────────── assets
@app.post("/v3/assets")
async def upload_asset(request: Request):
    if not _auth_ok(request):
        return _deny()
    await request.body()
    return {"data": {"id": "asset_" + uuid.uuid4().hex[:12],
                     "asset_id": "asset_" + uuid.uuid4().hex[:12],
                     "url": "https://mock.local/asset.bin"}}


@app.post("/v1/asset")
async def upload_asset_v1(request: Request):
    return await upload_asset(request)


# ─────────────────────────────────────────────── avatars
@app.get("/v2/avatars")
async def list_avatars(request: Request):
    if not _auth_ok(request):
        return _deny()
    return {"data": {"avatars": [
        {"avatar_id": "mock_av_anna", "avatar_name": "Анна (тест)",
         "gender": "female",
         "preview_image_url": "https://api.dicebear.com/7.x/personas/png?seed=anna"},
        {"avatar_id": "mock_av_ivan", "avatar_name": "Иван (тест)",
         "gender": "male",
         "preview_image_url": "https://api.dicebear.com/7.x/personas/png?seed=ivan"},
        {"avatar_id": "mock_av_maria", "avatar_name": "Мария (тест)",
         "gender": "female",
         "preview_image_url": "https://api.dicebear.com/7.x/personas/png?seed=maria"},
    ]}}


@app.get("/v2/avatar_group.list")
async def list_groups(request: Request):
    if not _auth_ok(request):
        return _deny()
    return {"data": {"avatar_groups": [
        {"group_id": "grp_mock_1", "group_name": "Моя тестовая группа"}]}}


@app.post("/v3/avatars")
async def create_avatar(request: Request):
    if not _auth_ok(request):
        return _deny()
    body = await request.json()
    aid = "look_" + uuid.uuid4().hex[:12]
    _AVATARS[aid] = {"created": time.time(), "type": body.get("type", "photo"),
                     "name": body.get("name", "")}
    return {"data": {
        "avatar_item": {"id": aid, "avatar_type": "photo_avatar",
                        "group_id": "grp_" + uuid.uuid4().hex[:8],
                        "supported_api_engines": ["avatar_iv", "avatar_v"]},
        "avatar_group": {"id": "grp_" + uuid.uuid4().hex[:8], "consent_status": None},
    }}


@app.post("/v2/photo_avatar/avatar_group/create")
async def create_photo_group(request: Request):
    if not _auth_ok(request):
        return _deny()
    aid = "pa_" + uuid.uuid4().hex[:12]
    _AVATARS[aid] = {"created": time.time(), "type": "photo"}
    return {"data": {"id": aid, "group_id": "grp_" + uuid.uuid4().hex[:8],
                     "status": "pending"}}


@app.get("/v2/photo_avatar/{avatar_id}")
async def get_photo_avatar(avatar_id: str, request: Request):
    if not _auth_ok(request):
        return _deny()
    rec = _AVATARS.get(avatar_id, {"created": time.time() - 99})
    ready = (time.time() - rec["created"]) > AVATAR_READY_AFTER
    return {"data": {"id": avatar_id, "avatar_id": avatar_id,
                     "status": "completed" if ready else "pending",
                     "image_url": "https://mock.local/avatar.png"}}


@app.get("/v3/avatars/{avatar_id}")
async def get_avatar_v3(avatar_id: str, request: Request):
    return await get_photo_avatar(avatar_id, request)


# ── генерация фото-аватара по описанию
@app.post("/v2/photo_avatar/photo/generate")
async def generate_photo(request: Request):
    if not _auth_ok(request):
        return _deny()
    body = await request.json()
    gid = "gen_" + uuid.uuid4().hex[:12]
    _GENPHOTOS[gid] = {"created": time.time(), "body": body}
    return {"data": {"generation_id": gid, "status": "pending"}}


@app.get("/v2/photo_avatar/generation/{generation_id}")
async def get_generation(generation_id: str, request: Request):
    if not _auth_ok(request):
        return _deny()
    rec = _GENPHOTOS.get(generation_id, {"created": time.time() - 99})
    ready = (time.time() - rec["created"]) > PHOTO_READY_AFTER
    if not ready:
        return {"data": {"id": generation_id, "status": "pending"}}
    return {"data": {"id": generation_id, "status": "success", "image_url_list": [
        f"https://api.dicebear.com/7.x/personas/png?seed={generation_id}{i}"
        for i in range(4)
    ], "image_key_list": [f"image/{generation_id}_{i}/original" for i in range(4)]}}


# ─────────────────────────────────────────────── voices
@app.get("/v2/voices")
async def list_voices(request: Request):
    if not _auth_ok(request):
        return _deny()
    return {"data": {"voices": [
        {"voice_id": "mock_ru_female", "name": "Светлана (рус)",
         "display_name": "Светлана (рус)", "language": "Russian", "gender": "female",
         "support_pause": True, "emotion_support": True,
         "preview_audio": "https://mock.local/preview1.mp3"},
        {"voice_id": "mock_ru_male", "name": "Дмитрий (рус)",
         "display_name": "Дмитрий (рус)", "language": "Russian", "gender": "male",
         "support_pause": True, "emotion_support": True,
         "preview_audio": "https://mock.local/preview2.mp3"},
        {"voice_id": "mock_en_female", "name": "Emily (eng)",
         "display_name": "Emily (eng)", "language": "English", "gender": "female",
         "support_pause": True, "emotion_support": False,
         "preview_audio": "https://mock.local/preview3.mp3"},
    ]}}


@app.get("/v3/voices")
async def list_voices_v3(request: Request):
    return await list_voices(request)


@app.post("/v2/voices/design")
async def design_voice(request: Request):
    if not _auth_ok(request):
        return _deny()
    body = await request.json()
    return {"data": {"voices": [
        {"voice_id": "designed_" + uuid.uuid4().hex[:8],
         "name": f"Дизайн: {body.get('prompt','')[:24]}",
         "preview_audio": "https://mock.local/designed.mp3"}
        for _ in range(2)
    ]}}


@app.post("/v2/voice/clone")
async def clone_voice(request: Request):
    if not _auth_ok(request):
        return _deny()
    cid = "clone_" + uuid.uuid4().hex[:12]
    _CLONES[cid] = {"created": time.time()}
    return {"data": {"voice_clone_id": cid, "status": "pending"}}


@app.get("/v2/voice/clone/{clone_id}")
async def get_clone(clone_id: str, request: Request):
    if not _auth_ok(request):
        return _deny()
    rec = _CLONES.get(clone_id, {"created": time.time() - 99})
    ready = (time.time() - rec["created"]) > CLONE_READY_AFTER
    return {"data": {"voice_clone_id": clone_id,
                     "status": "completed" if ready else "training",
                     "voice_id": ("voice_cloned_" + clone_id[-8:]) if ready else None}}


# ─────────────────────────────────────────────── TTS
@app.post("/v2/tts/generate")
async def tts(request: Request):
    if not _auth_ok(request):
        return _deny()
    return {"data": {"audio_id": "aud_" + uuid.uuid4().hex[:10],
                     "status": "completed",
                     "audio_url": "https://mock.local/tts.mp3"}}


# ─────────────────────────────────────────────── videos
@app.post("/v3/videos")
async def create_video(request: Request):
    if not _auth_ok(request):
        return _deny()
    body = await request.json()
    if not body.get("avatar_id"):
        return JSONResponse({"error": {"message": "avatar_id is required"}},
                            status_code=400)
    has_audio = bool(body.get("script") or body.get("audio_asset_id")
                     or body.get("audio_url"))
    if not has_audio:
        return JSONResponse(
            {"error": {"message": "script or audio source is required"}},
            status_code=400)
    vid = "vid_" + uuid.uuid4().hex[:12]
    _VIDEOS[vid] = {"created": time.time(), "payload": body}
    return {"data": {"video_id": vid}}


@app.get("/v3/videos/{video_id}")
async def get_video(video_id: str, request: Request):
    if not _auth_ok(request):
        return _deny()
    rec = _VIDEOS.get(video_id)
    if not rec:
        return JSONResponse({"error": {"message": "video not found"}}, status_code=404)
    elapsed = time.time() - rec["created"]
    if elapsed < VIDEO_READY_AFTER:
        return {"data": {"id": video_id, "video_id": video_id, "status": "processing",
                         "progress": round(min(elapsed / VIDEO_READY_AFTER * 100, 99), 1)}}
    return {"data": {"id": video_id, "video_id": video_id, "status": "completed",
                     "progress": 100,
                     "video_url": f"http://127.0.0.1:8765/mock-file/{video_id}.mp4",
                     "thumbnail_url": "https://mock.local/thumb.jpg",
                     "subtitle_url": f"http://127.0.0.1:8765/mock-file/{video_id}.srt",
                     "duration": 15.0}}


@app.get("/v1/video_status.get")
async def get_video_v1(video_id: str, request: Request):
    return await get_video(video_id, request)


@app.get("/mock-file/{name}")
async def mock_file(name: str):
    """Отдаёт настоящий маленький mp4/srt, чтобы проверить скачивание."""
    if name.endswith(".srt"):
        srt = ("1\n00:00:00,000 --> 00:00:03,000\n"
               "Тестовые субтитры из мок-сервера.\n")
        return Response(srt.encode("utf-8"), media_type="application/x-subrip")
    if _SAMPLE_MP4.is_file():
        return Response(_SAMPLE_MP4.read_bytes(), media_type="video/mp4")
    return Response(_PNG_1x1, media_type="video/mp4")


@app.get("/v3/wallet")
async def wallet(request: Request):
    if not _auth_ok(request):
        return _deny()
    return {"data": {"balance": 999, "currency": "credits", "mock": True}}


@app.get("/")
async def root():
    return {"mock": True, "service": "HeyGen API emulator", "ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
