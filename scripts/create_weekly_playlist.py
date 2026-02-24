"""Create a weekly Spotify playlist using GitHub Models + Spotify API."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SPOTIFY_ACCOUNTS_BASE = "https://accounts.spotify.com"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
GITHUB_MODELS_BASE = "https://models.inference.ai.azure.com"
DEFAULT_USER_PROMPT_FILE = "prompts/playlist_user_prompt.md"
DEFAULT_MODEL = "gpt-5-mini"
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def read_file_if_exists(path: str) -> str | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8")


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    form: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", **(headers or {})}

    data: bytes | None = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    elif form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request) as response:
                content = response.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as err:
            details = err.read().decode("utf-8", errors="replace")
            # Retry on 429 (rate limit) and 5xx (server errors)
            if err.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = RETRY_BACKOFF * (attempt + 1)
                print(
                    f"HTTP {err.code} on attempt {attempt + 1}/{retries}. "
                    f"Retrying in {wait:.1f}s…",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            print(f"HTTP error {err.code} for {method} {url}: {details}", file=sys.stderr)
            raise

    # Should not be reached, but satisfies type checker
    raise RuntimeError(f"All {retries} retries exhausted for {method} {url}")


def spotify_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = http_json(
        "POST",
        f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
        headers={"Authorization": f"Basic {basic}"},
        form={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    return response["access_token"]


def build_model_prompts(top_tracks: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the model request."""
    system_prompt = (
        "You are a music curator writing weekly playlist descriptions. "
        "When given a user's recent listening data, you respond only with a valid JSON object "
        'containing exactly one key: "description" (one short paragraph, no emojis). '
        "Do not include markdown, code fences, or any other text."
    )

    prompt_file = os.getenv("PLAYLIST_PROMPT_FILE", DEFAULT_USER_PROMPT_FILE)
    user_template = read_file_if_exists(prompt_file) or (
        "Create metadata for a weekly Spotify playlist based on my recent listening.\n"
        "Top artists: {top_artists}.\n"
        "Top tracks: {top_tracks}.\n"
        "Return strict JSON with keys title and description."
    )

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
        top_artists=top_artists or "Unknown",
        top_tracks=top_track_names or "Unknown",
    )
    return system_prompt, user_prompt


def model_playlist_metadata(
    gh_token: str,
    model_name: str,
    top_tracks: list[dict[str, Any]],
    temperature: float,
) -> dict[str, str]:
    system_prompt, user_prompt = build_model_prompts(top_tracks)

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
    except json.JSONDecodeError as exc:
        print(f"Model returned invalid JSON: {raw_content!r}", file=sys.stderr)
        raise ValueError("Model response was not valid JSON.") from exc

    description = str(parsed.get("description", "")).strip() or "Generated automatically."

    return {"description": description}
def spotify_get_me(token: str) -> dict[str, Any]:
    return http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me",
        headers={"Authorization": f"Bearer {token}"},
    )


def spotify_get_top_tracks(token: str, limit: int = 15) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"time_range": "short_term", "limit": str(limit)})
    payload = http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me/top/tracks?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return payload.get("items", [])


def spotify_get_top_artists(token: str, limit: int = 10) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"time_range": "short_term", "limit": str(limit)})
    payload = http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me/top/artists?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return payload.get("items", [])


def spotify_search_tracks_by_genre(token: str, genre: str, limit: int = 10) -> list[str]:
    params = urllib.parse.urlencode({
        "q": f"genre:{genre}",
        "type": "track",
        "limit": str(limit),
    })
    try:
        payload = http_json(
            "GET",
            f"{SPOTIFY_API_BASE}/search?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        return [t["uri"] for t in payload.get("tracks", {}).get("items", []) if t.get("uri")]
    except Exception:
        return []


def spotify_get_discovery_tracks(
    token: str,
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    limit: int = 30,
) -> list[str]:
    # Collect known track URIs to avoid duplicates
    known_uris: set[str] = {t["uri"] for t in top_tracks if t.get("uri")}

    # Extract unique genres from top artists
    genres: list[str] = list(dict.fromkeys(
        genre
        for artist in top_artists
        for genre in artist.get("genres", [])
    ))

    if not genres:
        # Fall back to searching by artist name if no genres available
        genres = [f'artist:"{a["name"]}"' for a in top_artists[:5]]

    discovery_uris: list[str] = []
    for genre in genres:
        if len(discovery_uris) >= limit:
            break
        tracks = spotify_search_tracks_by_genre(token, genre, limit=10)
        for uri in tracks:
            if uri not in known_uris and uri not in discovery_uris:
                discovery_uris.append(uri)

    return discovery_uris[:limit]


def spotify_create_playlist(
    token: str, user_id: str, name: str, description: str
) -> str:
    payload = http_json(
        "POST",
        f"{SPOTIFY_API_BASE}/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": name, "description": description, "public": False},
    )
    return payload["id"]


def spotify_add_tracks(token: str, playlist_id: str, uris: list[str]) -> None:
    # Spotify allows a maximum of 100 tracks per request
    for i in range(0, len(uris), 100):
        http_json(
            "POST",
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {token}"},
            body={"uris": uris[i : i + 100]},
        )


def main() -> None:
    spotify_client_id = require_env("SPOTIFY_CLIENT_ID")
    spotify_client_secret = require_env("SPOTIFY_CLIENT_SECRET")
    spotify_refresh_token = require_env("SPOTIFY_REFRESH_TOKEN")
    github_token = require_env("GITHUB_TOKEN")

    model_name = os.getenv("GITHUB_MODEL", DEFAULT_MODEL)
    model_temperature = float(os.getenv("GITHUB_MODEL_TEMPERATURE", "0.8"))
    top_tracks_limit = int(os.getenv("SPOTIFY_TOP_TRACKS_LIMIT", "15"))
    recommendation_limit = int(os.getenv("SPOTIFY_RECOMMENDATIONS_LIMIT", "30"))

    print("Authenticating with Spotify…")
    token = spotify_access_token(spotify_client_id, spotify_client_secret, spotify_refresh_token)
    me = spotify_get_me(token)
    user_id: str = me["id"]

    print("Fetching top tracks and artists…")
    top_tracks = spotify_get_top_tracks(token, limit=top_tracks_limit)
    top_artists = spotify_get_top_artists(token, limit=10)
    if len(top_tracks) < 5:
        print(
            f"Not enough listening history — got {len(top_tracks)} tracks, need at least 5.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Fetching discovery tracks via genre search…")
    rec_uris = spotify_get_discovery_tracks(token, top_tracks, top_artists, limit=recommendation_limit)
    if not rec_uris:
        print("No discovery tracks found.", file=sys.stderr)
        sys.exit(1)

    print("Generating playlist metadata with AI…")
    playlist_meta = model_playlist_metadata(
        github_token,
        model_name,
        top_tracks,
        model_temperature,
    )

    week = dt.date.today().isocalendar()
    playlist_name = f"{week.year}-W{week.week:02d}"
    playlist_description = playlist_meta["description"]

    print("Creating playlist…")
    playlist_id = spotify_create_playlist(token, user_id, playlist_name, playlist_description)
    spotify_add_tracks(token, playlist_id, rec_uris)

    print(f"\n✓ Created playlist: {playlist_name}")
    print(f"  https://open.spotify.com/playlist/{playlist_id}")


if __name__ == "__main__":
    main()