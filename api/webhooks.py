"""
Webhook receiver for HeyGen callbacks.
HeyGen sends POST requests here when videos/translations/tts complete.
"""

import logging
from fastapi import APIRouter, Request, HTTPException, Header

from models.schemas import WebhookPayload

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory store for recent webhook events (use Redis in production)
_recent_events: list[dict] = []
_MAX_EVENTS = 100


@router.post("/heygen")
async def heygen_webhook(
    request: Request,
    x_signature: str | None = Header(default=None),
):
    """
    Receive webhook callbacks from HeyGen.
    Events: avatar_video.success, avatar_video.failed,
            video_agent.success, video_agent.failed, etc.
    """
    try:
        body = await request.json()
    except Exception:
        body = {"raw_body": (await request.body()).decode()}

    payload = WebhookPayload(**body) if isinstance(body, dict) else WebhookPayload(event_type="unknown")

    event = {
        "event_type": payload.event_type,
        "video_id": payload.video_id,
        "session_id": payload.session_id,
        "status": payload.status,
        "video_url": payload.video_url,
        "error": payload.error,
    }

    # Store event
    _recent_events.insert(0, event)
    if len(_recent_events) > _MAX_EVENTS:
        _recent_events.pop()

    logger.info(f"[Webhook] {payload.event_type}: video={payload.video_id} status={payload.status}")

    # TODO: Add your custom business logic here
    # e.g., notify user, update database, trigger next workflow step

    return {"received": True}


@router.get("/events")
async def list_recent_events(limit: int = 20):
    """List recent webhook events (for debugging)."""
    return {"events": _recent_events[:limit]}
