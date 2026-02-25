"""Multi-user config loader from GitHub Secrets environment variables."""

from __future__ import annotations

import os
from typing import NamedTuple


class UserCredentials(NamedTuple):
    """Spotify user credentials."""

    username: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_refresh_token: str


def load_users_from_env() -> list[UserCredentials]:
    """Load Spotify user credentials from environment variables.

    Global credentials (shared across all users):
        SPOTIFY_CLIENT_ID=...
        SPOTIFY_CLIENT_SECRET=...

    Per-user refresh tokens:
        SPOTIFY_USER_REFRESH_TOKEN_HENRY_JOHNSON=...
        SPOTIFY_USER_REFRESH_TOKEN_JANE_DOE=...
        etc.

    Returns a list of UserCredentials.
    """
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print(
            "⚠ SPOTIFY_CLIENT_ID and/or SPOTIFY_CLIENT_SECRET not set.",
            flush=True,
        )
        return []

    prefix = "SPOTIFY_USER_REFRESH_TOKEN_"
    users = []

    for key, value in sorted(os.environ.items()):
        if not key.startswith(prefix):
            continue
        if not value.strip():
            continue

        # SPOTIFY_USER_REFRESH_TOKEN_HENRY_JOHNSON → "Henry Johnson"
        raw = key[len(prefix):]  # e.g. "HENRY_JOHNSON"
        username = raw.replace("_", " ").title()  # e.g. "Henry Johnson"

        users.append(
            UserCredentials(
                username=username,
                spotify_client_id=client_id,
                spotify_client_secret=client_secret,
                spotify_refresh_token=value.strip(),
            )
        )

    return users
