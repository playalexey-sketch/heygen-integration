"""Video translation routes."""

from fastapi import APIRouter

from heygen_client import HeyGenClient
from models.schemas import TranslationRequest

router = APIRouter()


@router.post("")
async def translate_video(req: TranslationRequest):
    """Translate a video to another language with lip-sync."""
    client = HeyGenClient()
    result = client.translate_video(
        video_url=req.video_url,
        target_language=req.target_language,
        mode=req.mode,
        callback_url=req.callback_url,
    )
    return result.model_dump()


@router.get("/{translation_id}/status")
async def get_translation_status(translation_id: str):
    """Get translation job status."""
    client = HeyGenClient()
    return client.get_translation(translation_id).model_dump()
