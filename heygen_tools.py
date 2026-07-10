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

Help:
  heygen_help() — Show this help
"""
