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

    Expected format:
        SPOTIFY_USER_HENRY_CLIENT_ID=...
        SPOTIFY_USER_HENRY_CLIENT_SECRET=...
        SPOTIFY_USER_HENRY_REFRESH_TOKEN=...
        etc.

    Returns a list of UserCredentials.
    """
    users_dict: dict[str, dict[str, str]] = {}

    # Scan environment for SPOTIFY_USER_* variables
    for key, value in os.environ.items():
        if not key.startswith("SPOTIFY_USER_"):
            continue

        # Parse: SPOTIFY_USER_{USERNAME}_{FIELD}
        parts = key.split("_")
        if len(parts) < 5:
            continue

        username = parts[2]
        field = "_".join(parts[3:]).lower()  # e.g., "client_id", "client_secret"

        if username not in users_dict:
            users_dict[username] = {}

        users_dict[username][field] = value

    # Validate and convert to UserCredentials
    users = []
    for username, creds in sorted(users_dict.items()):
        required_fields = {"client_id", "client_secret", "refresh_token"}
        if not required_fields.issubset(creds.keys()):
            missing = required_fields - set(creds.keys())
            print(
                f"⚠ User '{username}' missing credentials: {missing}",
                flush=True,
            )
            continue

        users.append(
            UserCredentials(
                username=username,
                spotify_client_id=creds["client_id"],
                spotify_client_secret=creds["client_secret"],
                spotify_refresh_token=creds["refresh_token"],
            )
        )

    return users
