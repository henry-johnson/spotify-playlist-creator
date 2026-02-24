"""Spotify Web API helpers."""

from __future__ import annotations

import datetime as dt
import sys
import urllib.error
import urllib.parse
from typing import Any

from config import SPOTIFY_API_BASE, SPOTIFY_PLAYLIST_DESCRIPTION_MAX
from http_client import http_json


# ── User profile ────────────────────────────────────────────────────


def spotify_get_me(token: str) -> dict[str, Any]:
    """Get the current user's profile."""
    return http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me",
        headers={"Authorization": f"Bearer {token}"},
    )


# ── Top items ───────────────────────────────────────────────────────


def spotify_get_top_tracks(token: str, limit: int = 15) -> list[dict[str, Any]]:
    """Get the user's top tracks (short_term)."""
    params = urllib.parse.urlencode(
        {"time_range": "short_term", "limit": str(limit)},
    )
    payload = http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me/top/tracks?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return payload.get("items", [])


def spotify_get_top_artists(token: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get the user's top artists (short_term)."""
    params = urllib.parse.urlencode(
        {"time_range": "short_term", "limit": str(limit)},
    )
    payload = http_json(
        "GET",
        f"{SPOTIFY_API_BASE}/me/top/artists?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return payload.get("items", [])


# ── Week labelling ──────────────────────────────────────────────────


def iso_week_label(day: dt.date) -> str:
    """Return an ISO week label like '2026-W09'."""
    week = day.isocalendar()
    return f"{week.year}-W{week.week:02d}"


# ── Playlist CRUD ───────────────────────────────────────────────────


def spotify_find_playlist_by_name(
    token: str, name: str, owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Find a playlist by exact name. Returns the first match or None."""
    params = urllib.parse.urlencode({"limit": "50"})
    next_url: str | None = f"{SPOTIFY_API_BASE}/me/playlists?{params}"

    while next_url:
        payload = http_json(
            "GET",
            next_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        for playlist in payload.get("items", []):
            if playlist.get("name") != name:
                continue

            if owner_id:
                playlist_owner = (playlist.get("owner") or {}).get("id")
                if playlist_owner != owner_id:
                    continue

                return playlist
        next_url = payload.get("next")

    return None


def spotify_get_playlist_tracks(
    token: str, playlist_id: str, limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch tracks from a playlist (paginated)."""
    params = urllib.parse.urlencode({"limit": "100"})
    next_url: str | None = (
        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?{params}"
    )
    tracks: list[dict[str, Any]] = []

    while next_url and len(tracks) < limit:
        payload = http_json(
            "GET",
            next_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        for item in payload.get("items", []):
            track = item.get("track") or {}
            if track.get("uri"):
                tracks.append(track)
            if len(tracks) >= limit:
                break
        next_url = payload.get("next")

    return tracks


def _normalize_description(description: str) -> str:
    """Normalize a playlist description. Warns if over Spotify's limit."""
    normalized = " ".join(description.split()).strip()
    if not normalized:
        return "Generated automatically."

    if len(normalized) > SPOTIFY_PLAYLIST_DESCRIPTION_MAX:
        print(
            f"Warning: description is {len(normalized)} chars "
            f"(Spotify limit is {SPOTIFY_PLAYLIST_DESCRIPTION_MAX}).",
            file=sys.stderr,
            flush=True,
        )

    return normalized


def spotify_create_playlist(
    token: str, name: str, description: str,
) -> str:
    """Create a new private playlist. Returns the playlist ID."""
    payload = http_json(
        "POST",
        f"{SPOTIFY_API_BASE}/me/playlists",
        headers={"Authorization": f"Bearer {token}"},
        body={
            "name": name,
            "description": _normalize_description(description),
            "public": False,
        },
    )
    return payload["id"]


def spotify_clear_playlist(token: str, playlist_id: str) -> int:
    """Remove all tracks from a playlist. Returns the count removed."""
    def _first_page() -> dict[str, Any]:
        return http_json(
            "GET",
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?limit=100",
            headers={"Authorization": f"Bearer {token}"},
        )

    payload = _first_page()
    total_before = int(payload.get("total") or 0)
    if total_before == 0:
        return 0

    # Fast path: replace all playlist items with an empty list.
    # Spotify historically used /tracks for this endpoint; newer docs use /items.
    for replace_endpoint in ("tracks", "items"):
        try:
            http_json(
                "PUT",
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/{replace_endpoint}",
                headers={"Authorization": f"Bearer {token}"},
                body={"uris": []},
            )
            break
        except urllib.error.HTTPError as err:
            if err.code in (400, 403, 404, 405):
                continue
            raise

    payload = _first_page()
    if int(payload.get("total") or 0) == 0:
        return total_before

    # Fallback path: repeatedly delete the first page by explicit positions
    # until Spotify reports the playlist is empty.
    while True:
        items = payload.get("items", [])
        if not items:
            break

        tracks_batch: list[dict[str, Any]] = []
        for position, item in enumerate(items):
            track = item.get("track") or {}
            uri = track.get("uri")
            if uri:
                tracks_batch.append({"uri": uri, "positions": [position]})

        if not tracks_batch:
            break

        http_json(
            "DELETE",
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {token}"},
            body={"tracks": tracks_batch},
        )
        payload = _first_page()

    remaining = int(payload.get("total") or 0)
    if remaining > 0:
        raise RuntimeError(
            f"Could not fully clear playlist {playlist_id}; "
            f"{remaining} items remain.",
        )

    return total_before


def spotify_update_playlist_details(
    token: str, playlist_id: str, name: str, description: str,
) -> None:
    """Update the name and description of an existing playlist."""
    http_json(
        "PUT",
        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
        headers={"Authorization": f"Bearer {token}"},
        body={
            "name": name,
            "description": _normalize_description(description),
            "public": False,
        },
    )


def spotify_add_tracks(
    token: str, playlist_id: str, uris: list[str],
) -> int:
    """Add tracks to a playlist, with per-track fallback on 403.

    Returns the number of tracks successfully added.
    """

    def _add_batch_with_query(batch_uris: list[str]) -> None:
        params = urllib.parse.urlencode({"uris": ",".join(batch_uris)})
        http_json(
            "POST",
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )

    added_count = 0
    for i in range(0, len(uris), 100):
        batch = uris[i : i + 100]
        try:
            http_json(
                "POST",
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items",
                headers={"Authorization": f"Bearer {token}"},
                body={"uris": batch},
            )
            added_count += len(batch)
            continue
        except urllib.error.HTTPError as err:
            if err.code != 403:
                raise

            try:
                _add_batch_with_query(batch)
                added_count += len(batch)
                continue
            except urllib.error.HTTPError as query_err:
                if query_err.code != 403:
                    raise

            print(
                f"Batch add returned 403. "
                f"Retrying one-by-one for {len(batch)} tracks…",
                file=sys.stderr,
                flush=True,
            )
            for uri in batch:
                try:
                    _add_batch_with_query([uri])
                    added_count += 1
                except urllib.error.HTTPError as single_err:
                    if single_err.code == 403:
                        print(
                            f"Skipping forbidden track URI: {uri}",
                            file=sys.stderr,
                            flush=True,
                        )
                        continue
                    raise

    return added_count


# ── Search ──────────────────────────────────────────────────────────


def spotify_search_tracks(
    token: str,
    query: str,
    limit: int = 10,
    market: str | None = None,
) -> list[str]:
    """Search Spotify for tracks. Returns a list of track URIs."""
    query_params: dict[str, str] = {
        "q": query,
        "type": "track",
        "limit": str(limit),
    }
    if market:
        query_params["market"] = market

    params = urllib.parse.urlencode(query_params)
    try:
        payload = http_json(
            "GET",
            f"{SPOTIFY_API_BASE}/search?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        uris = [
            t["uri"]
            for t in payload.get("tracks", {}).get("items", [])
            if t.get("uri")
        ]
        print(f"  Search '{query}': {len(uris)} tracks", flush=True)
        return uris
    except Exception as exc:
        print(f"  Search '{query}' failed: {exc}", file=sys.stderr)
        return []


# ── Track helpers ───────────────────────────────────────────────────


def artists_from_tracks(
    tracks: list[dict[str, Any]], limit: int = 10,
) -> list[dict[str, Any]]:
    """Extract the most-frequent artists from a list of tracks."""
    counts: dict[str, int] = {}
    artist_payload: dict[str, dict[str, Any]] = {}

    for track in tracks:
        for artist in track.get("artists", []):
            name = artist.get("name")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            if name not in artist_payload:
                artist_payload[name] = {
                    "name": name,
                    "genres": [],
                    "id": artist.get("id"),
                }

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [artist_payload[name] for name, _ in ordered[:limit]]
