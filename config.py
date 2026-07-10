"""
HeyGen Integration — Configuration
All sensitive settings come from environment variables.
"""

import os
from functools import lru_cache


class Settings:
    """Application settings loaded from environment."""

    # ── HeyGen API ──────────────────────────────────────────────
    HEYGEN_API_KEY: str = os.getenv("HEYGEN_API_KEY", "")
    HEYGEN_BASE_URL: str = os.getenv("HEYGEN_BASE_URL", "https://api.heygen.com")

    # ── Webhook ─────────────────────────────────────────────────
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    CALLBACK_URL: str = os.getenv("CALLBACK_URL", "")

    # ── Server ──────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # ── UI ──────────────────────────────────────────────────────
    UI_PORT: int = int(os.getenv("UI_PORT", "8501"))

    @property
    def headers(self) -> dict:
        """Default headers for HeyGen API requests."""
        return {
            "X-Api-Key": self.HEYGEN_API_KEY,
            "Content-Type": "application/json",
        }

    def validate(self) -> None:
        """Ensure critical settings are present."""
        if not self.HEYGEN_API_KEY:
            raise ValueError(
                "HEYGEN_API_KEY is required. "
                "Set it in .env file or environment variable."
            )


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
