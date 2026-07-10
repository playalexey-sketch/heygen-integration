"""Avatar routes."""

from fastapi import APIRouter, HTTPException

from heygen_client import HeyGenClient

router = APIRouter()


@router.get("")
async def list_avatars():
    """Get all available avatars."""
    client = HeyGenClient()
    return {"avatars": [a.model_dump() for a in client.list_avatars()]}


@router.get("/{avatar_id}")
async def get_avatar(avatar_id: str):
    """Get avatar details."""
    client = HeyGenClient()
    return client.get_avatar(avatar_id).model_dump()


@router.get("/groups/list")
async def list_avatar_groups():
    """Get all avatar groups."""
    client = HeyGenClient()
    return {"groups": [g.model_dump() for g in client.list_avatar_groups()]}


@router.get("/groups/{group_id}/avatars")
async def list_group_avatars(group_id: str):
    """Get avatars in a specific group."""
    client = HeyGenClient()
    return {"avatars": [a.model_dump() for a in client.list_group_avatars(group_id)]}
