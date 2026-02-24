"""AI-powered playlist artwork generation via GitHub Models."""

from __future__ import annotations

import base64
import binascii
import os
import sys
import urllib.request
from typing import Any

from config import (
    DEFAULT_ARTWORK_PROMPT_FILE,
    GITHUB_MODELS_BASE,
    SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES,
    read_file_if_exists,
)
from http_client import http_json


def _default_artwork_prompt_template() -> str:
    """Fallback prompt for playlist artwork generation."""
    return (
        "Create square album-cover-style artwork for a weekly Spotify playlist.\n"
        "Target week: {target_week}\n"
        "Source week: {source_week}\n"
        "Top artists: {top_artists}\n"
        "Top tracks: {top_tracks}\n"
        "Style notes: modern, moody, musical, abstract, no text, no logos, "
        "no faces.\n"
        "Output should be suitable as a playlist cover image."
    )


def _build_artwork_prompt(
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
) -> str:
    """Build the user prompt for image generation."""
    prompt_file = os.getenv("PLAYLIST_ARTWORK_PROMPT_FILE", DEFAULT_ARTWORK_PROMPT_FILE)
    template = read_file_if_exists(prompt_file) or _default_artwork_prompt_template()

    artist_names = ", ".join(
        dict.fromkeys(
            [a.get("name", "") for a in top_artists if a.get("name")]
            + [
                artist.get("name", "")
                for track in top_tracks
                for artist in track.get("artists", [])
                if artist.get("name")
            ]
        )
    )
    track_names = ", ".join(
        track.get("name", "") for track in top_tracks[:12] if track.get("name")
    )

    return template.format(
        source_week=source_week,
        target_week=target_week,
        top_artists=artist_names or "Unknown",
        top_tracks=track_names or "Unknown",
    )


def _extract_base64_image(response: dict[str, Any]) -> str | None:
    """Extract base64 image data from an OpenAI-compatible image response."""
    data = response.get("data")
    if not isinstance(data, list) or not data:
        return None

    first = data[0]
    if not isinstance(first, dict):
        return None

    b64_json = first.get("b64_json")
    if isinstance(b64_json, str) and b64_json.strip():
        return b64_json.strip()

    image_url = first.get("url")
    if isinstance(image_url, str) and image_url.strip():
        try:
            with urllib.request.urlopen(image_url) as resp:
                raw = resp.read()
            return base64.b64encode(raw).decode("ascii")
        except Exception as exc:
            print(f"  Artwork fetch failed: {exc}", file=sys.stderr, flush=True)
            return None

    return None


def _artwork_model_available(gh_token: str, model_name: str) -> bool:
    """Check whether the configured artwork model is visible in the catalog."""
    try:
        payload = http_json(
            "GET",
            f"{GITHUB_MODELS_BASE}/catalog/models",
            headers={
                "Authorization": f"Bearer {gh_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    except Exception as exc:
        print(
            f"  Could not verify model catalog ({exc}); trying {model_name} anyway.",
            file=sys.stderr,
            flush=True,
        )
        return True

    if not isinstance(payload, list):
        return True

    model_ids = {
        str(item.get("id") or "").strip()
        for item in payload
        if isinstance(item, dict)
    }
    return model_name in model_ids


def generate_playlist_artwork_base64(
    gh_token: str,
    model_name: str,
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
) -> str | None:
    """Generate playlist artwork and return base64-encoded JPEG bytes.

    Returns None on failure or if image validation fails.
    """
    prompt = _build_artwork_prompt(
        top_tracks,
        top_artists,
        source_week=source_week,
        target_week=target_week,
    )

    if not _artwork_model_available(gh_token, model_name):
        print(
            f"  Artwork model '{model_name}' is not available for this token; "
            "skipping artwork.",
            file=sys.stderr,
            flush=True,
        )
        return None

    print(f"  Artwork AI: calling {model_name}…", flush=True)

    try:
        response = http_json(
            "POST",
            f"{GITHUB_MODELS_BASE}/images/generations",
            headers={"Authorization": f"Bearer {gh_token}"},
            body={
                "model": model_name,
                "prompt": prompt,
                "size": "512x512",
                "quality": "low",
                "output_format": "jpeg",
            },
        )
    except Exception as exc:
        print(f"  Artwork AI failed: {exc}", file=sys.stderr, flush=True)
        return None

    image_b64 = _extract_base64_image(response)
    if not image_b64:
        print("  Artwork AI returned no image payload.", file=sys.stderr, flush=True)
        return None

    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        print("  Artwork payload was not valid base64.", file=sys.stderr, flush=True)
        return None

    if len(image_bytes) > SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES:
        print(
            "  Artwork too large for Spotify upload "
            f"({len(image_bytes)} bytes > {SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES}).",
            file=sys.stderr,
            flush=True,
        )
        return None

    return base64.b64encode(image_bytes).decode("ascii")
