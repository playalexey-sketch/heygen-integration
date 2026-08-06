"""
HeyGen Tools — Direct-call functions for AI agent integration.

These functions are designed to be called directly from an AI assistant
(like me) to create videos, translations, and speech without managing
HTTP requests manually.

Usage from agent:
    from heygen_tools import (
        heygen_create_video, heygen_list_avatars, heygen_list_voices,
        heygen_translate_video, heygen_text_to_speech,
    )

All functions return plain dicts with the result for easy display.
"""

import os
from typing import Optional

from heygen_client import HeyGenClient, HeyGenError


def _client() -> HeyGenClient:
    """Get a fresh client instance."""
    return HeyGenClient()


# ═══════════════════════════════════════════════════════════════
# VIDEO CREATION
# ═══════════════════════════════════════════════════════════════

def heygen_create_video(
    script: str,
    avatar_id: str = "",
    voice_id: str = "",
    background: Optional[str] = None,
    width: int = 1920,
    height: int = 1080,
    wait: bool = True,
    poll_interval: int = 10,
    timeout: int = 600,
) -> dict:
    """
    Create an AI avatar video with the given script.

    Args:
        script: The text the avatar will speak.
        avatar_id: Avatar ID. If empty, uses first available.
        voice_id: Voice ID. If empty, uses first available.
        background: Background color or image URL.
        width: Video width (default 1920).
        height: Video height (default 1080).
        wait: If True, polls until video is ready.
        poll_interval: Seconds between status checks.
        timeout: Max seconds to wait.

    Returns:
        dict with video_id, status, video_url, etc.
    """
    client = _client()

    # Auto-select avatar/voice if not provided
    if not avatar_id:
        avatars = client.list_avatars()
        if not avatars:
            return {"error": "No avatars available"}
        avatar_id = avatars[0].avatar_id

    if not voice_id:
        voices = client.list_voices()
        if not voices:
            return {"error": "No voices available"}
        voice_id = voices[0].voice_id

    # Create video
    result = client.create_avatar_video(
        avatar_id=avatar_id,
        voice_id=voice_id,
        script=script,
        background=background,
        width=width,
        height=height,
    )

    output = result.model_dump()
    output["avatar_used"] = avatar_id
    output["voice_used"] = voice_id

    # Wait for completion if requested
    if wait and result.video_id:
        try:
            final = client.poll_video(result.video_id, interval=poll_interval, timeout=timeout)
            output.update(final.model_dump())
        except HeyGenError as e:
            output["polling_error"] = str(e)

    return output


def heygen_create_video_agent(
    prompt: str,
    wait: bool = True,
    poll_interval: int = 10,
    timeout: int = 600,
) -> dict:
    """
    Create a video using Video Agent (prompt-based autonomous generation).

    Args:
        prompt: Description of the desired video.
        wait: If True, polls until video is ready.
        poll_interval: Seconds between checks.
        timeout: Max seconds to wait.

    Returns:
        dict with session_id, video_id, video_url, status.
    """
    client = _client()
    result = client.create_video_agent(prompt=prompt)
    output = result.model_dump()

    if wait and result.session_id:
        try:
            final = client.poll_video_agent(result.session_id, interval=poll_interval, timeout=timeout)
            output.update(final.model_dump())
        except HeyGenError as e:
            output["polling_error"] = str(e)

    return output


# ═══════════════════════════════════════════════════════════════
# PHOTO → VIDEO AGENT (photo avatar + voice)
# ═══════════════════════════════════════════════════════════════

def heygen_create_photo_video(
    photo_path: Optional[str] = None,
    photo_url: Optional[str] = None,
    photo_asset_id: Optional[str] = None,
    audio_path: Optional[str] = None,
    audio_url: Optional[str] = None,
    audio_asset_id: Optional[str] = None,
    script: Optional[str] = None,
    voice_id: Optional[str] = None,
    clone_voice_from: Optional[str] = None,
    voice_name: str = "My Cloned Voice",
    avatar_name: str = "My Photo Avatar",
    title: str = "",
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    background: Optional[str] = None,
    motion_prompt: Optional[str] = None,
    wait: bool = True,
    poll_interval: int = 10,
    timeout: int = 600,
) -> dict:
    """
    Build a video from a photo and a voice (digital avatar on the photo).

    Give the avatar's face with ONE of: photo_path / photo_url / photo_asset_id.
    Give the voice with ONE of:
      * audio_path / audio_url / audio_asset_id  -> avatar lip-syncs the audio
      * script (+ voice_id)                       -> avatar speaks the text
      * clone_voice_from (local audio path) + script
        -> clones your voice, then speaks the text with it

    Returns a dict with avatar_id, voice_used, video_id, video_url, status.
    """
    client = _client()
    result: dict = {}

    # ── 1. Photo avatar ────────────────────────────────────────
    if photo_asset_id:
        image_asset_id = photo_asset_id
    elif photo_path:
        asset = client.upload_asset(photo_path)
        image_asset_id = asset.asset_id
    elif photo_url:
        image_asset_id = None
    else:
        return {"error": "Provide a photo: photo_path, photo_url or photo_asset_id."}

    avatar = client.create_photo_avatar(
        name=avatar_name,
        image_asset_id=image_asset_id,
        image_url=photo_url,
    )
    avatar_id = avatar.avatar_id
    result["avatar_id"] = avatar_id
    result["avatar_status"] = avatar.status
    if not avatar_id:
        return {"error": f"Failed to create photo avatar: {avatar.error or 'unknown error'}"}

    # Wait until the photo avatar is ready (recommended before generating video).
    try:
        avatar = client.poll_photo_avatar(avatar_id)
        result["avatar_status"] = avatar.status
        if avatar.status != "completed":
            return {"error": f"Photo avatar not ready: {avatar.error or avatar.status}"}
    except HeyGenError as e:
        # Some photo avatars become usable immediately; don't hard-fail.
        result["avatar_polling_error"] = str(e)

    # ── 2. Voice ───────────────────────────────────────────────
    voice_used = ""
    final_voice_id = voice_id or ""

    if audio_asset_id or audio_url:
        # Audio-driven: lip-sync the uploaded audio directly.
        final_audio_asset_id = audio_asset_id
        final_audio_url = audio_url
        if audio_path:
            asset = client.upload_asset(audio_path)
            final_audio_asset_id = asset.asset_id
        result["voice_mode"] = "audio"
    elif clone_voice_from:
        # Clone the uploaded voice, then use TTS with the script.
        asset = client.upload_asset(clone_voice_from)
        clone = client.clone_voice(
            voice_name=voice_name,
            audio_asset_id=asset.asset_id,
        )
        clone_status = client.poll_voice_clone(clone.voice_clone_id)
        if clone_status.status != "completed" or not clone_status.voice_id:
            return {"error": f"Voice clone failed: {clone_status.error or clone_status.status}"}
        final_voice_id = clone_status.voice_id
        voice_used = final_voice_id
        result["voice_mode"] = "cloned"
    else:
        # Plain TTS with a library voice (voice_id may be empty -> default voice).
        result["voice_mode"] = "tts"

    # ── 3. Create video ────────────────────────────────────────
    video = client.create_photo_video(
        avatar_id=avatar_id,
        voice_id=final_voice_id,
        script=script,
        audio_asset_id=final_audio_asset_id if result.get("voice_mode") == "audio" else None,
        audio_url=final_audio_url if result.get("voice_mode") == "audio" else None,
        title=title,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        background=background,
        motion_prompt=motion_prompt,
    )
    output = video.model_dump()
    output["avatar_id"] = avatar_id
    if voice_used:
        output["voice_used"] = voice_used

    # ── 4. Wait for completion ─────────────────────────────────
    if wait and video.video_id:
        try:
            final = client.poll_video(video.video_id, interval=poll_interval, timeout=timeout)
            output.update(final.model_dump())
        except HeyGenError as e:
            output["polling_error"] = str(e)

    return output


def heygen_create_photo_avatar(
    name: str,
    photo_path: Optional[str] = None,
    photo_url: Optional[str] = None,
    photo_asset_id: Optional[str] = None,
    wait: bool = True,
) -> dict:
    """Create a reusable photo avatar from a photo."""
    client = _client()
    if photo_asset_id:
        image_asset_id = photo_asset_id
    elif photo_path:
        asset = client.upload_asset(photo_path)
        image_asset_id = asset.asset_id
    elif photo_url:
        image_asset_id = None
    else:
        return {"error": "Provide photo_path, photo_url or photo_asset_id."}

    avatar = client.create_photo_avatar(
        name=name,
        image_asset_id=image_asset_id,
        image_url=photo_url,
    )
    output = avatar.model_dump()
    if wait and avatar.avatar_id:
        try:
            final = client.poll_photo_avatar(avatar.avatar_id)
            output.update(final.model_dump())
        except HeyGenError as e:
            output["polling_error"] = str(e)
    return output


def heygen_clone_voice(
    voice_name: str,
    audio_path: Optional[str] = None,
    audio_url: Optional[str] = None,
    audio_asset_id: Optional[str] = None,
    language: Optional[str] = None,
    wait: bool = True,
) -> dict:
    """Clone a voice from an audio sample."""
    client = _client()
    if audio_asset_id:
        asset_id = audio_asset_id
    elif audio_path:
        asset = client.upload_asset(audio_path)
        asset_id = asset.asset_id
    else:
        asset_id = None

    clone = client.clone_voice(
        voice_name=voice_name,
        audio_asset_id=asset_id,
        audio_url=audio_url,
        language=language,
    )
    output = clone.model_dump()
    if wait and clone.voice_clone_id:
        try:
            final = client.poll_voice_clone(clone.voice_clone_id)
            output.update(final.model_dump())
        except HeyGenError as e:
            output["polling_error"] = str(e)
    return output


# ═══════════════════════════════════════════════════════════════
# LIST RESOURCES
# ═══════════════════════════════════════════════════════════════

def heygen_list_avatars() -> list[dict]:
    """Get list of all available avatars."""
    return [a.model_dump() for a in _client().list_avatars()]


def heygen_list_voices(language: str = "") -> list[dict]:
    """
    Get list of available voices.
    Optionally filter by language code (e.g. 'en', 'ru', 'es').
    """
    voices = _client().list_voices()
    result = [v.model_dump() for v in voices]
    if language:
        result = [v for v in result if language.lower() in v.get("language", "").lower()]
    return result


def heygen_get_wallet() -> dict:
    """Get current wallet balance and info."""
    return _client().get_wallet()


# ═══════════════════════════════════════════════════════════════
# VIDEO MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def heygen_get_video(video_id: str) -> dict:
    """Get status and metadata of a specific video."""
    return _client().get_video(video_id).model_dump()


def heygen_list_videos(limit: int = 20) -> list[dict]:
    """List recent videos."""
    return [v.model_dump() for v in _client().list_videos(limit=limit)]


def heygen_delete_video(video_id: str) -> dict:
    """Delete a video."""
    _client().delete_video(video_id)
    return {"deleted": True, "video_id": video_id}


# ═══════════════════════════════════════════════════════════════
# TRANSLATION
# ═══════════════════════════════════════════════════════════════

def heygen_translate_video(
    video_url: str,
    target_language: str,
    mode: str = "speed",
    wait: bool = True,
) -> dict:
    """
    Translate a video to another language with lip-sync.

    Args:
        video_url: URL of the source video.
        target_language: Target language code (e.g. 'es', 'ru', 'zh').
        mode: 'speed' (faster, cheaper) or 'precision' (higher quality).
        wait: If True, polls until translation is ready.

    Returns:
        dict with translation_id, status, translated_video_url.
    """
    client = _client()
    result = client.translate_video(
        video_url=video_url,
        target_language=target_language,
        mode=mode,
    )
    output = result.model_dump()

    if wait and result.translation_id:
        import time
        start = time.time()
        while time.time() - start < 600:
            status = client.get_translation(result.translation_id)
            if status.status in ("completed", "failed"):
                output.update(status.model_dump())
                break
            time.sleep(10)

    return output


# ═══════════════════════════════════════════════════════════════
# TEXT-TO-SPEECH
# ═══════════════════════════════════════════════════════════════

def heygen_text_to_speech(
    text: str,
    voice_id: str = "",
    speed: float = 1.0,
    wait: bool = True,
) -> dict:
    """
    Convert text to speech audio.

    Args:
        text: Text to speak.
        voice_id: Voice ID. If empty, uses first available.
        speed: Speaking speed (0.5 - 2.0).
        wait: If True, polls until audio is ready.

    Returns:
        dict with audio_id, audio_url, status.
    """
    client = _client()

    if not voice_id:
        voices = client.list_voices()
        if not voices:
            return {"error": "No voices available"}
        voice_id = voices[0].voice_id

    result = client.text_to_speech(text=text, voice_id=voice_id, speed=speed)
    output = result.model_dump()
    output["voice_used"] = voice_id

    if wait and result.audio_id:
        try:
            final = client.poll_tts(result.audio_id)
            output.update(final.model_dump())
        except HeyGenError as e:
            output["polling_error"] = str(e)

    return output


# ═══════════════════════════════════════════════════════════════
# QUICK HELP
# ═══════════════════════════════════════════════════════════════

def heygen_help() -> str:
    """Return help text with available functions."""
    return """
Available HeyGen functions:

Video Creation:
  heygen_create_video(script, avatar_id, voice_id) — Create avatar video
  heygen_create_video_agent(prompt) — Create video from prompt (Video Agent)

Resources:
  heygen_list_avatars() — List available avatars
  heygen_list_voices(language) — List available voices
  heygen_get_wallet() — Check API balance

Video Management:
  heygen_get_video(video_id) — Get video status
  heygen_list_videos(limit) — List videos
  heygen_delete_video(video_id) — Delete a video

Translation:
  heygen_translate_video(video_url, target_language) — Translate video

Text-to-Speech:
  heygen_text_to_speech(text, voice_id) — Convert text to speech

Photo → Video agent:
  heygen_create_photo_video(photo_path, audio_path/script) — Video from a photo + voice
  heygen_create_photo_avatar(name, photo_path) — Create a photo avatar
  heygen_clone_voice(voice_name, audio_path) — Clone a voice from audio

Help:
  heygen_help() — Show this help
"""
