"""Video generation and management routes."""

from fastapi import APIRouter, HTTPException

from heygen_client import HeyGenClient, HeyGenError
from models.schemas import VideoRequest, VideoAgentRequest

router = APIRouter()


# ── Avatar Video ──────────────────────────────────────────────

@router.post("/create")
async def create_video(req: VideoRequest):
    """Create an avatar video with specified avatar, voice and script."""
    client = HeyGenClient()
    result = client.create_avatar_video(
        avatar_id=req.avatar_id,
        voice_id=req.voice_id,
        script=req.script,
        background=req.background,
        width=req.dimension.width,
        height=req.dimension.height,
        callback_url=req.callback_url,
    )
    return result.model_dump()


@router.get("/{video_id}/status")
async def get_video_status(video_id: str):
    """Get video status and metadata."""
    client = HeyGenClient()
    return client.get_video(video_id).model_dump()


@router.get("/{video_id}/poll")
async def poll_video(video_id: str, interval: int = 10, timeout: int = 600):
    """Poll video until complete (blocking)."""
    client = HeyGenClient()
    return client.poll_video(video_id, interval=interval, timeout=timeout).model_dump()


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    """Delete a video."""
    client = HeyGenClient()
    client.delete_video(video_id)
    return {"deleted": True, "video_id": video_id}


@router.get("")
async def list_videos(limit: int = 20, offset: int = 0):
    """List all videos."""
    client = HeyGenClient()
    return {"videos": [v.model_dump() for v in client.list_videos(limit, offset)]}


# ── Video Agent ───────────────────────────────────────────────

@router.post("/agent/create")
async def create_video_agent(req: VideoAgentRequest):
    """Create a video via Video Agent (prompt-based)."""
    client = HeyGenClient()
    result = client.create_video_agent(
        prompt=req.prompt,
        callback_url=req.callback_url,
    )
    return result.model_dump()


@router.get("/agent/{session_id}/status")
async def get_video_agent_status(session_id: str):
    """Get Video Agent session status."""
    client = HeyGenClient()
    return client.get_video_agent_status(session_id).model_dump()


@router.get("/agent/{session_id}/poll")
async def poll_video_agent(session_id: str, interval: int = 10, timeout: int = 600):
    """Poll Video Agent session until complete (blocking)."""
    client = HeyGenClient()
    return client.poll_video_agent(session_id, interval=interval, timeout=timeout).model_dump()
