"""Paths relative to the backend checkout; also resolve to /app in Docker."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BACKEND_DIR / "static"
UPLOAD_DIR = BACKEND_DIR / "uploads"
