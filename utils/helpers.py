"""
Helper utilities for HeyGen Integration.
"""

import os
import logging
from functools import wraps
from time import time

# ── Logging ───────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("heygen")


# ── Timing ────────────────────────────────────────────────────

def timed(func):
    """Decorator to log function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time()
        result = func(*args, **kwargs)
        elapsed = time() - start
        logging.getLogger("heygen").info(f"{func.__name__} took {elapsed:.2f}s")
        return result
    return wrapper


# ── File Helpers ──────────────────────────────────────────────

def ensure_dir(path: str) -> str:
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """Sanitize string for use as filename."""
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(c if c in keep else "_" for c in name)[:100]
