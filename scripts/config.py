"""Shared constants and environment helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Spotify ─────────────────────────────────────────────────────────
SPOTIFY_ACCOUNTS_BASE = "https://accounts.spotify.com"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_PLAYLIST_DESCRIPTION_MAX = 300

# ── GitHub Models ───────────────────────────────────────────────────
GITHUB_MODELS_BASE = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_RECOMMENDATIONS_MODEL = "gpt-4o"

# ── Prompt files ────────────────────────────────────────────────────
DEFAULT_USER_PROMPT_FILE = "prompts/playlist_user_prompt.md"
DEFAULT_RECOMMENDATIONS_PROMPT_FILE = "prompts/recommendations_prompt.md"

# ── Retry config ────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds


def require_env(name: str) -> str:
    """Return an environment variable or exit with an error."""
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def read_file_if_exists(path: str) -> str | None:
    """Read a text file if it exists, else return None."""
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8")
