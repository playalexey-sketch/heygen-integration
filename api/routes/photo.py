"""
Photo → Video agent routes (photo avatar + voice).

Endpoints accept multipart uploads (photo, audio) plus settings,
and orchestrate the full pipeline: upload → photo avatar → video.
"""

import os
import shutil
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from heygen_client import HeyGenClient
from heygen_tools import (
    heygen_create_photo_video,
    heygen_create_photo_avatar,
    heygen_clone_voice,
)
from models.schemas import PhotoAvatarRequest, PhotoVideoRequest, VoiceCloneRequest

router = APIRouter()

_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "heygen_photo_uploads")


def _save(upload: UploadFile | None) -> str | None:
    """Persist an uploaded file to disk and return its local path."""
    if upload is None:
        return None
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    safe_name = os.path.basename(upload.filename or "upload")
    path = os.path.join(_UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return path


@router.post("/video")
async def create_photo_video(
    photo: UploadFile | None = File(default=None, description="Portrait photo (PNG/JPG)"),
    audio: UploadFile | None = File(default=None, description="Voice audio (mp3/wav)"),
    name: str = Form(default="My Photo Avatar"),
    script: str = Form(default=""),
    voice_id: str = Form(default=""),
    voice_name: str = Form(default="My Voice"),
    title: str = Form(default=""),
    aspect_ratio: str = Form(default="16:9"),
    resolution: str = Form(default="1080p"),
    background: str = Form(default=""),
    motion_prompt: str = Form(default=""),
    duration_seconds: int = Form(default=15),
    clone_voice: bool = Form(default=False),
    wait: bool = Form(default=True),
):
    """
    Build a video from a photo + voice.

    * photo  -> creates a photo avatar (digital avatar on your photo)
    * audio  -> avatar lip-syncs the uploaded voice
    * script (+ voice_id) -> avatar speaks text
    * audio + clone_voice -> clones your voice, then speaks `script` with it
    """
    photo_path = _save(photo)
    audio_path = _save(audio)

    if photo_path is None:
        raise HTTPException(400, "No photo provided.")

    # Choose the voice strategy.
    if clone_voice and audio_path:
        if not script:
            raise HTTPException(400, "With voice cloning you must also provide a script.")
        result = heygen_create_photo_video(
            photo_path=photo_path,
            script=script,
            voice_id=voice_id,
            clone_voice_from=audio_path,
            voice_name=voice_name,
            avatar_name=name,
            title=title,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            background=background or None,
            motion_prompt=motion_prompt or None,
            wait=wait,
        )
    elif audio_path:
        result = heygen_create_photo_video(
            photo_path=photo_path,
            audio_path=audio_path,
            avatar_name=name,
            title=title,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            background=background or None,
            motion_prompt=motion_prompt or None,
            wait=wait,
        )
    elif script:
        result = heygen_create_photo_video(
            photo_path=photo_path,
            script=script,
            voice_id=voice_id,
            avatar_name=name,
            title=title,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            background=background or None,
            motion_prompt=motion_prompt or None,
            wait=wait,
        )
    else:
        raise HTTPException(400, "Provide an audio file or a script (+ voice_id).")

    # duration_seconds is informational for audio-driven videos (video length = audio length).
    result["requested_duration_seconds"] = duration_seconds

    if result.get("error"):
        raise HTTPException(500, result["error"])
    return result


@router.post("/asset")
async def upload_asset(file: UploadFile = File(...)):
    """Upload any file (image/audio/video/pdf) and get an asset_id."""
    path = _save(file)
    client = HeyGenClient()
    asset = client.upload_asset(path)
    if not asset.asset_id:
        raise HTTPException(500, "Asset upload failed.")
    return asset.model_dump()


@router.post("/avatar")
async def create_photo_avatar(req: PhotoAvatarRequest):
    """Create a photo avatar from an uploaded asset id or image URL."""
    client = HeyGenClient()
    return client.create_photo_avatar(
        name=req.name,
        image_asset_id=req.image_asset_id,
        image_url=req.image_url,
    ).model_dump()


@router.post("/voice/clone")
async def clone_voice(req: VoiceCloneRequest):
    """Clone a voice from an audio url / asset id."""
    client = HeyGenClient()
    result = client.clone_voice(
        voice_name=req.voice_name,
        audio_url=req.audio_url,
        audio_asset_id=req.audio_asset_id,
        language=req.language,
        remove_background_noise=req.remove_background_noise,
    )
    if result.voice_clone_id:
        try:
            final = client.poll_voice_clone(result.voice_clone_id)
            return final.model_dump()
        except Exception as e:  # noqa: BLE001
            return {**result.model_dump(), "polling_error": str(e)}
    return result.model_dump()
