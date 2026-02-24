"""AI-powered playlist description generation via GitHub Models."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from config import DEFAULT_USER_PROMPT_FILE, GITHUB_MODELS_BASE, read_file_if_exists
from http_client import http_json


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
    gh_token: str,
    model_name: str,
    top_tracks: list[dict[str, Any]],
    temperature: float,
    *,
    source_week: str,
    target_week: str,
    listener_first_name: str,
) -> str:
    """Generate a playlist description using an AI model.

    Returns the description string.
    """
    system_prompt, user_prompt = _build_description_prompts(
        top_tracks,
        source_week=source_week,
        target_week=target_week,
        first_name=listener_first_name,
    )

    try:
        response = http_json(
            "POST",
            f"{GITHUB_MODELS_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {gh_token}"},
            body={
                "model": model_name,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
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
        f"Weekly playlist for {target_week}, based on {source_week} listening"
        f"{': ' + fallback_artists if fallback_artists else ''}."
    )
