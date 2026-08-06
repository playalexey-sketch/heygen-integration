"""
Pydantic models for HeyGen API requests and responses.
"""

from typing import Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Avatars
# ═══════════════════════════════════════════════════════════════

class Avatar(BaseModel):
    """Represents a HeyGen avatar."""
    avatar_id: str = Field(..., description="Unique avatar identifier")
    avatar_name: str = Field(default="", description="Display name")
    gender: str = Field(default="", description="Gender: male / female")
    preview_image_url: Optional[str] = Field(default=None, description="Preview image")
    preview_video_url: Optional[str] = Field(default=None, description="Preview video")


class AvatarGroup(BaseModel):
    """Group of related avatars."""
    group_id: str
    group_name: str
    avatars: list[Avatar] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Voices
# ═══════════════════════════════════════════════════════════════

class Voice(BaseModel):
    """Represents a TTS voice."""
    voice_id: str = Field(..., description="Unique voice identifier")
    voice_name: str = Field(default="", description="Display name")
    language: str = Field(default="", description="Language code, e.g. en-US")
    gender: str = Field(default="", description="Gender: male / female")
    preview_audio_url: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Avatar Video Generation
# ═══════════════════════════════════════════════════════════════

class VideoDimension(BaseModel):
    """Video width and height."""
    width: int = 1920
    height: int = 1080


class VideoRequest(BaseModel):
    """Request body for creating an avatar video."""
    avatar_id: str = Field(..., description="Avatar to use")
    voice_id: str = Field(..., description="Voice to use")
    script: str = Field(..., min_length=1, description="Text to speak")
    background: Optional[str] = Field(default=None, description="Background color or URL")
    dimension: VideoDimension = Field(default_factory=VideoDimension)
    callback_url: Optional[str] = Field(default=None, description="Webhook URL for completion")


class VideoResponse(BaseModel):
    """Response after submitting a video creation request."""
    video_id: str = Field(..., description="Unique video identifier")
    status: str = Field(default="pending", description="pending / processing / completed / failed")
    video_url: Optional[str] = Field(default=None, description="Download URL when completed")
    thumbnail_url: Optional[str] = Field(default=None)
    duration: Optional[float] = Field(default=None, description="Duration in seconds")
    created_at: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None, description="Error message if failed")


class VideoStatus(BaseModel):
    """Detailed status of a video."""
    video_id: str
    status: str  # pending / processing / completed / failed
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration: Optional[float] = None
    progress: Optional[float] = Field(default=None, description="Progress 0-100")
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# Video Agent (Prompt → Video)
# ═══════════════════════════════════════════════════════════════

class VideoAgentRequest(BaseModel):
    """Request body for Video Agent (prompt-based generation)."""
    prompt: str = Field(..., min_length=1, description="Description of the desired video")
    callback_url: Optional[str] = Field(default=None, description="Webhook URL")


class VideoAgentResponse(BaseModel):
    """Response after submitting a Video Agent request."""
    session_id: str = Field(..., description="Session identifier for polling")
    status: str = Field(default="generating")
    video_id: Optional[str] = Field(default=None)
    video_url: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)


class VideoAgentStatus(BaseModel):
    """Status of a Video Agent session."""
    session_id: str
    status: str  # generating / completed / failed
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# Video Translation
# ═══════════════════════════════════════════════════════════════

class TranslationRequest(BaseModel):
    """Request body for video translation."""
    video_url: str = Field(..., description="URL of the source video")
    target_language: str = Field(..., description="Target language code, e.g. 'es' / 'ru' / 'zh'")
    mode: str = Field(default="speed", description="'speed' or 'precision'")
    callback_url: Optional[str] = Field(default=None)


class TranslationResponse(BaseModel):
    """Response after submitting a translation request."""
    translation_id: str = Field(..., description="Translation job identifier")
    status: str = Field(default="processing")
    translated_video_url: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Text-to-Speech
# ═══════════════════════════════════════════════════════════════

class TTSRequest(BaseModel):
    """Request body for text-to-speech generation."""
    text: str = Field(..., min_length=1, description="Text to convert to speech")
    voice_id: str = Field(..., description="Voice to use")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0, description="Speaking speed")


class TTSResponse(BaseModel):
    """Response after submitting a TTS request."""
    audio_id: str = Field(..., description="Audio file identifier")
    status: str = Field(default="processing")
    audio_url: Optional[str] = Field(default=None)
    duration: Optional[float] = Field(default=None)
    error: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Assets / Upload
# ═══════════════════════════════════════════════════════════════

class AssetUploadResponse(BaseModel):
    """Result of uploading a file via POST /v3/assets."""
    asset_id: str = Field(default="", description="ID to reference the asset")
    url: Optional[str] = Field(default=None, description="Public URL of the asset")
    mime_type: Optional[str] = Field(default=None)
    size_bytes: Optional[int] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Photo Avatar
# ═══════════════════════════════════════════════════════════════

class PhotoAvatarRequest(BaseModel):
    """Request to create a Photo Avatar (digital avatar from a photo)."""
    name: str = Field(..., min_length=1, description="Name for the photo avatar")
    image_asset_id: Optional[str] = Field(default=None, description="Uploaded asset id of the image")
    image_url: Optional[str] = Field(default=None, description="Public URL of the image (alternative to image_asset_id)")


class PhotoAvatarResponse(BaseModel):
    """Response after creating a photo avatar."""
    avatar_id: str = Field(..., description="Photo avatar id, usable as avatar_id for video generation")
    status: str = Field(default="processing", description="processing / completed / failed")
    preview_image_url: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Photo → Video (agent)
# ═══════════════════════════════════════════════════════════════

class PhotoVideoRequest(BaseModel):
    """Full request for the photo-to-video agent (photo avatar + voice)."""
    # Avatar source
    name: str = Field(default="My Photo Avatar", description="Photo avatar name")
    image_asset_id: Optional[str] = Field(default=None)
    image_url: Optional[str] = Field(default=None)

    # Voice: pick ONE of (a) uploaded audio, (b) text script + voice_id
    audio_asset_id: Optional[str] = Field(default=None, description="Uploaded audio asset id (audio-driven lip sync)")
    audio_url: Optional[str] = Field(default=None)
    script: Optional[str] = Field(default=None, description="Text the avatar speaks")
    voice_id: Optional[str] = Field(default=None, description="TTS voice id (required with script)")

    # Output settings
    title: str = Field(default="", description="Video title")
    aspect_ratio: str = Field(default="16:9", description="16:9, 9:16, 1:1 or auto")
    resolution: str = Field(default="1080p", description="720p or 1080p")
    background: Optional[str] = Field(default=None, description="Background color (hex) or URL")
    motion_prompt: Optional[str] = Field(default=None, description="Gesture/expression prompt for Avatar IV")

    # Orchestration
    wait: bool = Field(default=True, description="Block until the video is ready")
    poll_interval: int = Field(default=10, ge=1, le=120)
    timeout: int = Field(default=600, ge=10, le=3600)


# ═══════════════════════════════════════════════════════════════
# Voice Cloning
# ═══════════════════════════════════════════════════════════════

class VoiceCloneRequest(BaseModel):
    """Request to clone a voice from an audio file."""
    voice_name: str = Field(..., min_length=1, description="Display name for the cloned voice")
    audio_url: Optional[str] = Field(default=None)
    audio_asset_id: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None, description="Language hint, e.g. 'ru' or 'en'")
    remove_background_noise: bool = Field(default=True)


class VoiceCloneResponse(BaseModel):
    """Response after submitting a voice clone job."""
    voice_clone_id: str = Field(..., description="Job id to poll status")
    status: str = Field(default="processing")


class VoiceCloneStatus(BaseModel):
    """Status of a voice clone job."""
    voice_clone_id: str
    status: str  # processing / completed / failed
    voice_id: Optional[str] = Field(default=None, description="Final voice_id once completed")
    error: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Webhook
# ═══════════════════════════════════════════════════════════════

class WebhookPayload(BaseModel):
    """Incoming webhook payload from HeyGen."""
    event_type: str = Field(..., description="e.g. 'avatar_video.success' / 'avatar_video.failed'")
    video_id: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    video_url: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    created_at: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════
# Error
# ═══════════════════════════════════════════════════════════════

class ApiError(BaseModel):
    """Structured API error."""
    code: str
    message: str
    details: Optional[dict] = None
