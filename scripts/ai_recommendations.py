"""AI-powered music recommendation engine via GitHub Models.

Uses a large language model to generate intelligent Spotify search queries
based on the user's listening data, replacing Spotify's restricted
Recommendations API with an open, customisable alternative.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from config import (
    DEFAULT_RECOMMENDATIONS_PROMPT_FILE,
    GITHUB_MODELS_BASE,
    read_file_if_exists,
)
from http_client import http_json


def _default_prompt_template() -> str:
    """Fallback prompt when the prompt file is missing."""
    return (
        "Analyse my recent listening and suggest Spotify search queries "
        "for music discovery.\n\n"
        "Source week: {source_week}\n"
        "Target week: {target_week}\n\n"
        "My top artists:\n{top_artists}\n\n"
        "My top tracks:\n{top_tracks}\n\n"
        "Genres in rotation: {genres}\n\n"
        "Suggest {max_queries} Spotify search queries. "
        "Each query should use Spotify search syntax "
        '(supports: artist:"name", genre:"name", track:"name", '
        'album:"name", year:YYYY, year:YYYY-YYYY).\n\n'
        "Mix of:\n"
        "- 4-5 queries for artists SIMILAR to but DIFFERENT from my "
        "current rotation\n"
        "- 3-4 genre-adjacent or cross-genre queries\n"
        "- 2-3 queries for specific tracks or albums I'd likely enjoy\n"
        "- 2-3 left-field picks — surprising but defensible based on "
        "my listening pattern\n\n"
        "DO NOT suggest tracks or artists already in my listening data.\n"
        "Prefer queries that surface recent releases (last 2 years).\n"
        'Return strict JSON: {"queries": [...]}'
    )


def _build_recommendation_prompt(
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
    max_queries: int,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the recommendation engine."""
    system_prompt = (
        "You are a music discovery engine. "
        "Given a listener's recent listening data, you suggest Spotify search "
        "queries that will help them discover NEW music they haven't heard. "
        "You respond only with a valid JSON object containing exactly one key: "
        '"queries" (an array of Spotify search query strings). '
        "Do not include markdown, code fences, or any other text."
    )

    prompt_file = os.getenv(
        "RECOMMENDATIONS_PROMPT_FILE",
        DEFAULT_RECOMMENDATIONS_PROMPT_FILE,
    )
    user_template = read_file_if_exists(prompt_file) or _default_prompt_template()

    # Build rich data for placeholders
    artist_lines: list[str] = []
    for a in top_artists[:10]:
        genres = ", ".join(a.get("genres", [])[:5]) or "unknown"
        artist_lines.append(f"- {a.get('name', 'Unknown')} (genres: {genres})")

    track_lines: list[str] = []
    for t in top_tracks[:15]:
        artists = ", ".join(
            a.get("name", "") for a in t.get("artists", []) if a.get("name")
        )
        track_lines.append(
            f"- {t.get('name', 'Unknown')} by {artists or 'Unknown'}"
        )

    genres = list(
        dict.fromkeys(g for a in top_artists for g in a.get("genres", []))
    )

    user_prompt = user_template.format(
        source_week=source_week,
        target_week=target_week,
        top_artists="\n".join(artist_lines) or "No artist data available",
        top_tracks="\n".join(track_lines) or "No track data available",
        genres=", ".join(genres[:15]) or "unknown",
        max_queries=max_queries,
    )
    return system_prompt, user_prompt


def ai_recommend_search_queries(
    gh_token: str,
    model_name: str,
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
    temperature: float = 1.0,
    max_queries: int = 15,
) -> list[str]:
    """Use an AI model to generate Spotify search queries for music discovery.

    Returns a list of search query strings, or an empty list on failure.
    """
    system_prompt, user_prompt = _build_recommendation_prompt(
        top_tracks,
        top_artists,
        source_week=source_week,
        target_week=target_week,
        max_queries=max_queries,
    )

    print(f"  AI recommendations: calling {model_name}…", flush=True)

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
    except Exception as exc:
        print(
            f"  AI recommendations call failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return []

    raw_content = response["choices"][0]["message"]["content"]

    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        print(
            f"  AI recommendations returned invalid JSON: {raw_content[:200]!r}",
            file=sys.stderr,
            flush=True,
        )
        return []

    queries = parsed.get("queries", [])
    if not isinstance(queries, list):
        print(
            "  AI recommendations: 'queries' is not a list.",
            file=sys.stderr,
            flush=True,
        )
        return []

    # Filter to strings only
    queries = [q for q in queries if isinstance(q, str) and q.strip()]
    print(
        f"  AI recommendations: {len(queries)} search queries generated.",
        flush=True,
    )
    return queries[:max_queries]
