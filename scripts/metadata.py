"""AI-powered playlist description generation."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import Any

from model_provider import AIProvider
from config import (
    DEFAULT_USER_PROMPT_FILE,
    OPENAI_TEXT_MODEL_SMALL,
    OPENAI_TEMPERATURE_SMALL,
    SPOTIFY_PLAYLIST_DESCRIPTION_MAX,
    read_file_if_exists,
)


def _build_description_prompts(
    top_tracks: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
    first_name: str,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for playlist description generation."""
    system_prompt = (
        "You are a music curator writing weekly playlist descriptions. "
        "When given a user's recent listening data, you respond only with a valid JSON object "
        'containing exactly one key: "description" (one short paragraph, no emojis). '
        "The description MUST be 200 characters or fewer — Spotify enforces a hard limit. "
        "Do not include markdown, code fences, or any other text."
    )

    prompt_file = os.getenv("PLAYLIST_PROMPT_FILE", DEFAULT_USER_PROMPT_FILE)
    user_template = read_file_if_exists(prompt_file) or (
        "Create metadata for a weekly Spotify playlist based on my recent listening.\n"
        "Listener first name: {first_name}.\n"
        "Source week: {source_week}.\n"
        "Target week: {target_week}.\n"
        "Top artists: {top_artists}.\n"
        "Top tracks: {top_tracks}.\n"
        "Return strict JSON with a single key: description."
    )
    safe_first_name = first_name.strip() or "there"

    top_artists = ", ".join(
        dict.fromkeys(
            artist["name"]
            for track in top_tracks
            for artist in track.get("artists", [])
            if artist.get("name")
        )
    )
    top_track_names = ", ".join(
        track.get("name", "") for track in top_tracks if track.get("name")
    )

    user_prompt = user_template.format(
        first_name=safe_first_name,
        source_week=source_week,
        target_week=target_week,
        top_artists=top_artists or "Unknown",
        top_tracks=top_track_names or "Unknown",
    )
    return system_prompt, user_prompt


def generate_playlist_description(
    provider: AIProvider,
    top_tracks: list[dict[str, Any]],
    temperature: float,
    *,
    source_week: str,
    target_week: str,
    listener_first_name: str,
) -> str:
    """Generate a playlist description using an AI provider.

    Returns the description string.
    """
    system_prompt, user_prompt = _build_description_prompts(
        top_tracks,
        source_week=source_week,
        target_week=target_week,
        first_name=listener_first_name,
    )

    try:
        response = provider.generate_text(
            system_prompt,
            user_prompt,
            model=OPENAI_TEXT_MODEL_SMALL,
            temperature=OPENAI_TEMPERATURE_SMALL,
        )

        raw_content = response["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            print(f"Model returned invalid JSON: {raw_content!r}", file=sys.stderr)
            parsed = {}

        description = str(parsed.get("description", "")).strip()
        if description:
            return description
    except Exception as exc:
        print(
            f"  Description AI failed ({exc}); using fallback.",
            file=sys.stderr,
            flush=True,
        )

    # Fallback description when AI is unavailable or returns garbage
    fallback_artists = ", ".join(
        list(
            dict.fromkeys(
                artist["name"]
                for track in top_tracks[:5]
                for artist in track.get("artists", [])
                if artist.get("name")
            )
        )[:5]
    )
    return (
        f"Weekly playlist based on {source_week} listening"
        f"{': ' + fallback_artists if fallback_artists else ''}."
    )


def assemble_final_description(description_body: str) -> str:
    """Assemble the final Spotify playlist description and truncate to 300 chars.

    Format: "{description_body}. Playlist created at {timestamp}."
    Single source of truth used by both the production orchestrator and tests.
    """
    created_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    credits_suffix = f" This playlist was created by an AI experiment from Johnsons Technologies on {created_at}."
    body = " ".join(description_body.split()).strip().rstrip(".")

    full = f"{body}.{credits_suffix}"
    if len(full) <= SPOTIFY_PLAYLIST_DESCRIPTION_MAX:
        return full

    # Truncate body to fit everything within the limit
    available = SPOTIFY_PLAYLIST_DESCRIPTION_MAX - len(credits_suffix) - 1  # 1 for "."
    if available > 1:
        body = f"{body[:available - 1].rstrip()}…"
    else:
        body = body[:max(available, 0)]
    return f"{body}.{credits_suffix}"
