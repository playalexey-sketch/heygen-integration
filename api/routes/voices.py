"""Voice routes."""

from fastapi import APIRouter

from heygen_client import HeyGenClient

router = APIRouter()


@router.get("")
async def list_voices():
    """Get all available TTS voices."""
    client = HeyGenClient()
    return {"voices": [v.model_dump() for v in client.list_voices()]}
