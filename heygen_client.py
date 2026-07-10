"""
HeyGen Python SDK
Full-featured client for HeyGen API v2/v3.

Usage:
    from heygen_client import HeyGenClient

    client = HeyGenClient()  # reads HEYGEN_API_KEY from env
    video = client.create_avatar_video(
        avatar_id="YOUR_AVATAR_ID",
        voice_id="YOUR_VOICE_ID",
        script="Hello world!",
    )
    video_url = client.poll_video(video.video_id)
"""

import time
import logging
from typing import Optional

import requests

from config import get_settings
from models.schemas import (
    Avatar,
    AvatarGroup,
    Voice,
    VideoRequest,
    VideoResponse,
    VideoStatus,
    VideoAgentRequest,
    VideoAgentResponse,
    VideoAgentStatus,
    TranslationRequest,
    TranslationResponse,
    TTSRequest,
    TTSResponse,
    ApiError,
)

logger = logging.getLogger(__name__)


class HeyGenError(Exception):
    """Custom exception for HeyGen API errors."""
    def __init__(self, message: str, code: str = "", status_code: int = 0):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class HeyGenClient:
    """
    Official-style Python client for HeyGen API.
    Covers: Avatar Video, Video Agent, Translation, TTS, Avatars, Voices.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.HEYGEN_API_KEY
        self.base_url = (base_url or settings.HEYGEN_BASE_URL).rstrip("/")
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if not self.api_key:
            raise HeyGenError(
                "API key is required. Set HEYGEN_API_KEY environment variable."
            )

    # ═══════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════════

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an HTTP request to HeyGen API."""
        url = f"{self.base_url}{endpoint}"
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
                raise HeyGenError(
                    body.get("message", str(exc)),
                    code=body.get("code", ""),
                    status_code=status,
                )
            except (ValueError, KeyError):
                raise HeyGenError(str(exc), status_code=status)
        except requests.exceptions.RequestException as exc:
            raise HeyGenError(f"Network error: {exc}")

    # ═══════════════════════════════════════════════════════════
    # AVATARS
    # ═══════════════════════════════════════════════════════════

    def list_avatars(self) -> list[Avatar]:
        """Get all available avatars."""
        data = self._request("GET", "/v2/avatars")
        items = data.get("data", {}).get("avatars", [])
        return [Avatar(**a) for a in items]

    def get_avatar(self, avatar_id: str) -> Avatar:
        """Get details of a specific avatar."""
        data = self._request("GET", f"/v2/avatar/{avatar_id}/details")
        return Avatar(**data.get("data", {}))

    def list_avatar_groups(self) -> list[AvatarGroup]:
        """Get all avatar groups."""
        data = self._request("GET", "/v2/avatar_group.list")
        items = data.get("data", {}).get("avatar_groups", [])
        return [AvatarGroup(**g) for g in items]

    def list_group_avatars(self, group_id: str) -> list[Avatar]:
        """Get avatars in a specific group."""
        data = self._request("GET", f"/v2/avatar_group/{group_id}/avatars")
        items = data.get("data", {}).get("avatars", [])
        return [Avatar(**a) for a in items]

    # ═══════════════════════════════════════════════════════════
    # VOICES
    # ═══════════════════════════════════════════════════════════

    def list_voices(self) -> list[Voice]:
        """Get all available TTS voices."""
        data = self._request("GET", "/v2/voices")
        items = data.get("data", {}).get("voices", [])
        return [Voice(**v) for v in items]

    # ═══════════════════════════════════════════════════════════
    # AVATAR VIDEO GENERATION
    # ═══════════════════════════════════════════════════════════

    def create_avatar_video(
        self,
        avatar_id: str,
        voice_id: str,
        script: str,
        background: Optional[str] = None,
        width: int = 1920,
        height: int = 1080,
        callback_url: Optional[str] = None,
    ) -> VideoResponse:
        """
        Create an avatar video with specific avatar, voice and script.
        Returns immediately; use poll_video() to wait for completion.
        """
        payload: dict = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "voice_id": voice_id,
            "script": script,
            "engine": {"type": "avatar_v"},
            "dimension": {"width": width, "height": height},
        }
        if background:
            payload["background"] = background
        if callback_url:
            payload["callback_url"] = callback_url

        data = self._request("POST", "/v3/videos", json=payload)
        result = data.get("data", {})
        return VideoResponse(
            video_id=result.get("video_id", ""),
            status="processing",
        )

    def get_video(self, video_id: str) -> VideoStatus:
        """Get current status and metadata of a video."""
        data = self._request("GET", f"/v3/videos/{video_id}")
        result = data.get("data", {})
        return VideoStatus(
            video_id=result.get("id", video_id),
            status=result.get("status", "unknown"),
            video_url=result.get("video_url"),
            thumbnail_url=result.get("thumbnail_url"),
            duration=result.get("duration"),
            error=result.get("error"),
        )

    def delete_video(self, video_id: str) -> bool:
        """Delete a video."""
        self._request("DELETE", f"/v3/videos/{video_id}")
        return True

    def list_videos(self, limit: int = 20, offset: int = 0) -> list[VideoStatus]:
        """List all videos with pagination."""
        data = self._request("GET", "/v3/videos", params={"limit": limit, "offset": offset})
        items = data.get("data", {}).get("videos", [])
        return [
            VideoStatus(
                video_id=v.get("id", ""),
                status=v.get("status", "unknown"),
                video_url=v.get("video_url"),
                thumbnail_url=v.get("thumbnail_url"),
                duration=v.get("duration"),
                error=v.get("error"),
            )
            for v in items
        ]

    def poll_video(
        self,
        video_id: str,
        interval: int = 10,
        timeout: int = 600,
    ) -> VideoStatus:
        """
        Poll a video until it completes or fails.
        Returns the final VideoStatus with video_url on success.
        Raises HeyGenError on timeout.
        """
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_video(video_id)
            if status.status in ("completed", "failed"):
                return status
            logger.info(f"Video {video_id}: {status.status} — waiting {interval}s...")
            time.sleep(interval)
        raise HeyGenError(f"Timeout waiting for video {video_id}")

    def download_video(self, video_id: str, output_path: str) -> str:
        """
        Download the MP4 file of a completed video.
        Returns the local file path.
        """
        status = self.get_video(video_id)
        if not status.video_url:
            raise HeyGenError(f"Video {video_id} has no download URL. Status: {status.status}")

        resp = requests.get(status.video_url, timeout=120)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    # ═══════════════════════════════════════════════════════════
    # VIDEO AGENT (Prompt → Video)
    # ═══════════════════════════════════════════════════════════

    def create_video_agent(
        self,
        prompt: str,
        callback_url: Optional[str] = None,
    ) -> VideoAgentResponse:
        """
        Submit a prompt to Video Agent for autonomous video generation.
        Returns a session_id for polling.
        """
        payload: dict = {"prompt": prompt}
        if callback_url:
            payload["callback_url"] = callback_url

        data = self._request("POST", "/v3/video-agents", json=payload)
        result = data.get("data", {})
        return VideoAgentResponse(
            session_id=result.get("session_id", ""),
            status=result.get("status", "generating"),
            video_id=result.get("video_id"),
            video_url=result.get("video_url"),
        )

    def get_video_agent_status(self, session_id: str) -> VideoAgentStatus:
        """Poll Video Agent session status."""
        data = self._request("GET", f"/v3/video-agents/{session_id}")
        result = data.get("data", {})
        return VideoAgentStatus(
            session_id=result.get("session_id", session_id),
            status=result.get("status", "unknown"),
            video_id=result.get("video_id"),
            video_url=result.get("video_url"),
            error=result.get("error"),
        )

    def poll_video_agent(
        self,
        session_id: str,
        interval: int = 10,
        timeout: int = 600,
    ) -> VideoAgentStatus:
        """Poll Video Agent session until complete."""
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_video_agent_status(session_id)
            if status.status in ("completed", "failed"):
                return status
            logger.info(f"Agent session {session_id}: {status.status} — waiting {interval}s...")
            time.sleep(interval)
        raise HeyGenError(f"Timeout waiting for Video Agent session {session_id}")

    # ═══════════════════════════════════════════════════════════
    # VIDEO TRANSLATION
    # ═══════════════════════════════════════════════════════════

    def translate_video(
        self,
        video_url: str,
        target_language: str,
        mode: str = "speed",
        callback_url: Optional[str] = None,
    ) -> TranslationResponse:
        """
        Translate a video to another language with lip-sync.
        mode: 'speed' (faster, cheaper) or 'precision' (higher quality).
        """
        payload = {
            "video_url": video_url,
            "target_language": target_language,
            "mode": mode,
        }
        if callback_url:
            payload["callback_url"] = callback_url

        data = self._request("POST", "/v3/video-translate", json=payload)
        result = data.get("data", {})
        return TranslationResponse(
            translation_id=result.get("translation_id", ""),
            status=result.get("status", "processing"),
            translated_video_url=result.get("translated_video_url"),
            error=result.get("error"),
        )

    def get_translation(self, translation_id: str) -> TranslationResponse:
        """Get status of a translation job."""
        data = self._request("GET", f"/v3/video-translate/{translation_id}")
        result = data.get("data", {})
        return TranslationResponse(
            translation_id=result.get("translation_id", translation_id),
            status=result.get("status", "unknown"),
            translated_video_url=result.get("translated_video_url"),
            error=result.get("error"),
        )

    # ═══════════════════════════════════════════════════════════
    # TEXT-TO-SPEECH
    # ═══════════════════════════════════════════════════════════

    def text_to_speech(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
    ) -> TTSResponse:
        """Generate speech audio from text."""
        payload = {
            "text": text,
            "voice_id": voice_id,
            "speed": speed,
        }
        data = self._request("POST", "/v3/tts", json=payload)
        result = data.get("data", {})
        return TTSResponse(
            audio_id=result.get("audio_id", ""),
            status=result.get("status", "processing"),
            audio_url=result.get("audio_url"),
            duration=result.get("duration"),
            error=result.get("error"),
        )

    def get_tts(self, audio_id: str) -> TTSResponse:
        """Get status of a TTS job."""
        data = self._request("GET", f"/v3/tts/{audio_id}")
        result = data.get("data", {})
        return TTSResponse(
            audio_id=result.get("audio_id", audio_id),
            status=result.get("status", "unknown"),
            audio_url=result.get("audio_url"),
            duration=result.get("duration"),
            error=result.get("error"),
        )

    def poll_tts(
        self,
        audio_id: str,
        interval: int = 5,
        timeout: int = 120,
    ) -> TTSResponse:
        """Poll TTS until complete."""
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_tts(audio_id)
            if status.status in ("completed", "failed"):
                return status
            time.sleep(interval)
        raise HeyGenError(f"Timeout waiting for TTS {audio_id}")

    # ═══════════════════════════════════════════════════════════
    # WALLET / BALANCE
    # ═══════════════════════════════════════════════════════════

    def get_wallet(self) -> dict:
        """Get current wallet balance and info."""
        data = self._request("GET", "/v3/wallet")
        return data.get("data", {})
