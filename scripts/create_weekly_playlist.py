#!/usr/bin/env python3
"""Create a weekly Spotify playlist using GitHub Models + Spotify API."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SPOTIFY_ACCOUNTS_BASE = "https://accounts.spotify.com"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
GITHUB_MODELS_BASE = "https://models.inference.ai.azure.com"
DEFAULT_USER_PROMPT_FILE = "prompts/playlist_user_prompt.txt"
DEFAULT_SYSTEM_PROMPT = "You create concise and fun playlist metadata."


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

    try:
        with urllib.request.urlopen(request) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        details = err.read().decode("utf-8", errors="replace")
        print(f"HTTP error {err.code} for {method} {url}: {details}", file=sys.stderr)
        raise


def spotify_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    response = http_json(
        "POST",
        f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
        headers={"Authorization": f"Basic {basic}"},
        form={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    return response["access_token"]


def build_model_prompt(top_tracks: list[dict[str, Any]]) -> tuple[str, str]:
    system_prompt = os.getenv("PLAYLIST_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT

    default_template = read_file_if_exists(os.getenv("PLAYLIST_PROMPT_FILE", DEFAULT_USER_PROMPT_FILE)) or (
        "Create metadata for a weekly Spotify playlist. "
        "Top artists: {top_artists}. Top tracks: {top_tracks}. "
        "Return strict JSON with keys title and description."
    )
    template = os.getenv("PLAYLIST_PROMPT_TEMPLATE", default_template)

    top_artists = ", ".join(
        dict.fromkeys(
            artist["name"]
            for track in top_tracks
            for artist in track.get("artists", [])
            if artist.get("name")
        )
    )
    top_track_names = ", ".join(track.get("name", "") for track in top_tracks if track.get("name"))

    user_prompt = template.format(
        top_artists=top_artists or "Unknown",
        top_tracks=top_track_names or "Unknown",
    )
    return system_prompt, user_prompt


def model_playlist_prompt(
    gh_token: str,
    model_name: str,
    top_tracks: list[dict[str, Any]],
    temperature: float,
) -> dict[str, str]:
    system_prompt, user_prompt = build_model_prompt(top_tracks)
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

    content = response["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {
        "title": str(parsed.get("title", "Weekly Discovery")).strip() or "Weekly Discovery",
        "description": str(parsed.get("description", "Generated automatically.")).strip()
        or "Generated automatically.",
    }


def spotify_get_me(token: str) -> dict[str, Any]:
    return http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me",
        headers={"Authorization": f"Bearer {token}"},
    )


def spotify_get_top_tracks(token: str, limit: int = 15) -> list[dict[str, Any]]:
    payload = http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me/top/tracks?time_range=short_term&limit={limit}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return payload.get("items", [])


def spotify_get_recommendations(token: str, seed_tracks: list[str], limit: int = 30) -> list[str]:
    query = urllib.parse.urlencode(
        {
            "seed_tracks": ",".join(seed_tracks[:5]),
            "limit": str(limit),
        }
    )
    payload = http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/recommendations?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return [track["uri"] for track in payload.get("tracks", [])]


def spotify_create_playlist(token: str, user_id: str, name: str, description: str) -> str:
    payload = http_json(
        "POST",
        f"{SPOTIFY_API_BASE}/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": name, "description": description, "public": False},
    )
    return payload["id"]


def spotify_add_tracks(token: str, playlist_id: str, uris: list[str]) -> None:
    http_json(
        "POST",
        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
        headers={"Authorization": f"Bearer {token}"},
        body={"uris": uris},
    )


def main() -> None:
    spotify_client_id = require_env("SPOTIFY_CLIENT_ID")
    spotify_client_secret = require_env("SPOTIFY_CLIENT_SECRET")
    spotify_refresh_token = require_env("SPOTIFY_REFRESH_TOKEN")
    github_token = require_env("GITHUB_TOKEN")

    model_name = os.getenv("GITHUB_MODEL", "chatgpt-5.2")
    model_temperature = float(os.getenv("GITHUB_MODEL_TEMPERATURE", "0.8"))
    top_tracks_limit = int(os.getenv("SPOTIFY_TOP_TRACKS_LIMIT", "15"))
    recommendation_limit = int(os.getenv("SPOTIFY_RECOMMENDATIONS_LIMIT", "30"))

    token = spotify_access_token(spotify_client_id, spotify_client_secret, spotify_refresh_token)
    me = spotify_get_me(token)

    top_tracks = spotify_get_top_tracks(token, limit=top_tracks_limit)
    if len(top_tracks) < 5:
        print("Not enough listening history. Need at least 5 top tracks.", file=sys.stderr)
        sys.exit(1)

    seed_track_ids = [track["id"] for track in top_tracks if track.get("id")][:5]
    rec_uris = spotify_get_recommendations(token, seed_track_ids, limit=recommendation_limit)
    if not rec_uris:
        print("No recommendations returned by Spotify.", file=sys.stderr)
        sys.exit(1)

    playlist_meta = model_playlist_prompt(
        github_token,
        model_name,
        top_tracks,
        model_temperature,
    )

    week = dt.date.today().isocalendar()
    playlist_name = f"{playlist_meta['title']} · {week.year}-W{week.week:02d}"
    playlist_description = f"{playlist_meta['description']} | Generated by GitHub Actions + GitHub Models."

    playlist_id = spotify_create_playlist(token, me["id"], playlist_name, playlist_description)
    spotify_add_tracks(token, playlist_id, rec_uris)

    print(f"Created playlist: {playlist_name}")
    print(f"https://open.spotify.com/playlist/{playlist_id}")


if __name__ == "__main__":
    main()
