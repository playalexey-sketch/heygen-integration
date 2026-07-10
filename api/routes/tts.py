"""Text-to-Speech routes."""

from fastapi import APIRouter

from heygen_client import HeyGenClient
from models.schemas import TTSRequest

router = APIRouter()


@router.post("/create")
async def create_tts(req: TTSRequest):
    """Generate speech from text."""
    client = HeyGenClient()
    result = client.text_to_speech(
        text=req.text,
        voice_id=req.voice_id,
        speed=req.speed,
    )
    return result.model_dump()


@router.get("/{audio_id}/status")
async def get_tts_status(audio_id: str):
    """Get TTS job status."""
    client = HeyGenClient()
    return client.get_tts(audio_id).model_dump()
