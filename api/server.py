"""
FastAPI server for HeyGen Integration.
Provides REST API + Webhook receiver.

Run:
    uvicorn api.server:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from heygen_client import HeyGenClient, HeyGenError
from api.routes import avatars, voices, videos, translate, tts
from api import webhooks

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    settings.validate()
    yield


app = FastAPI(
    title="HeyGen Integration API",
    description="REST API wrapper for HeyGen video generation, translation, and TTS",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception handler ─────────────────────────────────────────

@app.exception_handler(HeyGenError)
async def heygen_error_handler(request: Request, exc: HeyGenError):
    return JSONResponse(
        status_code=exc.status_code or 500,
        content={"error": exc.code, "message": str(exc)},
    )

# ── Routers ───────────────────────────────────────────────────

app.include_router(avatars.router, prefix="/api/v1/avatars", tags=["Avatars"])
app.include_router(voices.router, prefix="/api/v1/voices", tags=["Voices"])
app.include_router(videos.router, prefix="/api/v1/videos", tags=["Videos"])
app.include_router(translate.router, prefix="/api/v1/translate", tags=["Translation"])
app.include_router(tts.router, prefix="/api/v1/tts", tags=["TTS"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])

# ── Health check ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "heygen-integration"}

@app.get("/")
async def root():
    return {
        "message": "HeyGen Integration API",
        "docs": "/docs",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
