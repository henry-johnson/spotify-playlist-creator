"""Create a weekly Spotify playlist using GitHub Models + Spotify API."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import random
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
DEFAULT_MODEL = "gpt-4o-mini"
SPOTIFY_PLAYLIST_DESCRIPTION_MAX = 300
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


REQUIRED_SCOPES = {
    "user-top-read",
    "playlist-modify-private",
    "playlist-modify-public",
}
OPTIONAL_SCOPES = {"playlist-read-private"}


def spotify_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> tuple[str, set[str]]:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = http_json(
        "POST",
        f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
        headers={"Authorization": f"Basic {basic}"},
        form={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )

    granted = set(response.get("scope", "").split())
    print(f"Granted scopes: {granted}", flush=True)
    missing = REQUIRED_SCOPES - granted
    if missing:
        print(
            f"ERROR: Token is missing required scope(s): {', '.join(sorted(missing))}\n"
            f"Re-authorise with scopes: {' '.join(sorted(REQUIRED_SCOPES))}\n"
            f"  https://accounts.spotify.com/authorize?response_type=code"
            f"&client_id={client_id}"
            f"&scope={'%20'.join(sorted(REQUIRED_SCOPES))}"
            f"&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback",
            file=sys.stderr,
        )
        sys.exit(1)

    missing_optional = OPTIONAL_SCOPES - granted
    if missing_optional:
        print(
            "Optional scope(s) missing: "
            f"{', '.join(sorted(missing_optional))}. "
            "Weekly dedupe and previous-playlist grounding will be disabled.",
            file=sys.stderr,
            flush=True,
        )

    return response["access_token"], granted


def build_model_prompts(
    top_tracks: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
) -> tuple[str, str]:
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
        "Source week: {source_week}.\n"
        "Target week: {target_week}.\n"
        "Top artists: {top_artists}.\n"
        "Top tracks: {top_tracks}.\n"
        "Return strict JSON with a single key: description."
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
        source_week=source_week,
        target_week=target_week,
        top_artists=top_artists or "Unknown",
        top_tracks=top_track_names or "Unknown",
    )
    return system_prompt, user_prompt


def model_playlist_metadata(
    gh_token: str,
    model_name: str,
    top_tracks: list[dict[str, Any]],
    temperature: float,
    *,
    source_week: str,
    target_week: str,
) -> dict[str, str]:
    system_prompt, user_prompt = build_model_prompts(
        top_tracks,
        source_week=source_week,
        target_week=target_week,
    )

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


def iso_week_label(day: dt.date) -> str:
    week = day.isocalendar()
    return f"{week.year}-W{week.week:02d}"


def spotify_find_playlist_by_name(token: str, name: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode({"limit": "50"})
    next_url: str | None = f"{SPOTIFY_API_BASE}/me/playlists?{params}"

    while next_url:
        payload = http_json(
            "GET",
            next_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        for playlist in payload.get("items", []):
            if playlist.get("name") == name:
                return playlist
        next_url = payload.get("next")

    return None


def spotify_get_playlist_tracks(token: str, playlist_id: str, limit: int = 100) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"limit": "100"})
    next_url: str | None = f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?{params}"
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


def artists_from_tracks(tracks: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    artist_payload: dict[str, dict[str, Any]] = {}

    for track in tracks:
        for artist in track.get("artists", []):
            name = artist.get("name")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
            if name not in artist_payload:
                artist_payload[name] = {"name": name, "genres": [], "id": artist.get("id")}

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [artist_payload[name] for name, _ in ordered[:limit]]


def spotify_search_tracks(
    token: str,
    query: str,
    limit: int = 10,
    market: str | None = None,
) -> list[str]:
    query_params = {
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
        uris = [t["uri"] for t in payload.get("tracks", {}).get("items", []) if t.get("uri")]
        print(f"  Search '{query}': {len(uris)} tracks", flush=True)
        return uris
    except Exception as exc:
        print(f"  Search '{query}' failed: {exc}", file=sys.stderr)
        return []


def spotify_get_discovery_tracks(
    token: str,
    source_tracks: list[dict[str, Any]],
    source_artists: list[dict[str, Any]],
    current_top_artists: list[dict[str, Any]],
    market: str | None = None,
) -> list[str]:
    """Build a discovery track mix: familiar anchors + genre/artist search."""
    known_uris: set[str] = {t["uri"] for t in source_tracks if t.get("uri")}
    discovered: list[str] = []
    discovered_set: set[str] = set()

    def add(uri: str, cap: int) -> bool:
        if uri not in known_uris and uri not in discovered_set and len(discovered) < cap:
            discovered.append(uri)
            discovered_set.add(uri)
            return True
        return False

    # --- Slot 1: Familiar anchors — shuffled source tracks, up to 10 ---
    anchor_uris = [t["uri"] for t in source_tracks if t.get("uri")]
    random.shuffle(anchor_uris)
    for uri in anchor_uris:
        if uri not in discovered_set and len(discovered) < 10:
            discovered.append(uri)
            discovered_set.add(uri)
    anchor_count = len(discovered)

    # --- Slot 2: Genre/artist search — fill to 28 ---
    # Genres come from current_top_artists (full objects from /me/top/artists with genre data).
    # Artist names come from both source and current top artists.
    genres = list(dict.fromkeys(
        g for a in current_top_artists for g in a.get("genres", [])
    ))
    artist_names = list(dict.fromkeys(
        [a["name"] for a in source_artists if a.get("name")]
        + [a["name"] for a in current_top_artists if a.get("name")]
    ))
    print(f"Genre search pool: {genres[:8]}", flush=True)
    print(f"Artist name search pool: {artist_names[:8]}", flush=True)
    queries = (
        [f'genre:"{g}"' for g in genres[:8]]
        + [f'artist:"{n}"' for n in artist_names[:8]]
    )
    for query in queries:
        if len(discovered) >= 28:
            break
        for uri in spotify_search_tracks(token, query, limit=10, market=market):
            add(uri, 28)
    search_count = len(discovered) - anchor_count

    print(
        f"Discovery mix: {len(discovered)} tracks (anchors={anchor_count}, search={search_count})",
        flush=True,
    )
    return discovered


def spotify_create_playlist(token: str, name: str, description: str) -> str:
    normalized_description = " ".join(description.split()).strip()
    if not normalized_description:
        normalized_description = "Generated automatically."

    if len(normalized_description) > SPOTIFY_PLAYLIST_DESCRIPTION_MAX:
        ellipsis = "…"
        trim_to = SPOTIFY_PLAYLIST_DESCRIPTION_MAX - len(ellipsis)
        truncated = normalized_description[:trim_to].rstrip()
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        normalized_description = (truncated or normalized_description[:trim_to]).rstrip() + ellipsis
        print(
            "Description exceeded Spotify limit; truncated before playlist creation.",
            file=sys.stderr,
            flush=True,
        )

    payload = http_json(
        "POST",
        f"{SPOTIFY_API_BASE}/me/playlists",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": name, "description": normalized_description, "public": False},
    )
    return payload["id"]


def spotify_clear_playlist(token: str, playlist_id: str) -> int:
    """Remove all tracks from a playlist. Returns the number of tracks removed."""
    next_url: str | None = f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?limit=100"
    all_uris: list[str] = []

    while next_url:
        payload = http_json(
            "GET",
            next_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        for item in payload.get("items", []):
            track = item.get("track") or {}
            uri = track.get("uri")
            if uri:
                all_uris.append(uri)
        next_url = payload.get("next")

    if not all_uris:
        return 0

    for i in range(0, len(all_uris), 100):
        batch = all_uris[i : i + 100]
        http_json(
            "DELETE",
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {token}"},
            body={"tracks": [{"uri": uri} for uri in batch]},
        )

    return len(all_uris)


def spotify_update_playlist_details(token: str, playlist_id: str, name: str, description: str) -> None:
    """Update the name and description of an existing playlist."""
    normalized_description = " ".join(description.split()).strip()
    if not normalized_description:
        normalized_description = "Generated automatically."

    if len(normalized_description) > SPOTIFY_PLAYLIST_DESCRIPTION_MAX:
        ellipsis = "\u2026"
        trim_to = SPOTIFY_PLAYLIST_DESCRIPTION_MAX - len(ellipsis)
        truncated = normalized_description[:trim_to].rstrip()
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        normalized_description = (truncated or normalized_description[:trim_to]).rstrip() + ellipsis
        print(
            "Description exceeded Spotify limit; truncated before playlist update.",
            file=sys.stderr,
            flush=True,
        )

    http_json(
        "PUT",
        f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": name, "description": normalized_description},
    )


def spotify_add_tracks(token: str, playlist_id: str, uris: list[str]) -> int:
    def add_batch_with_query(batch_uris: list[str]) -> None:
        params = urllib.parse.urlencode({"uris": ",".join(batch_uris)})
        http_json(
            "POST",
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )

    # Spotify allows a maximum of 100 tracks per request
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
                add_batch_with_query(batch)
                added_count += len(batch)
                continue
            except urllib.error.HTTPError as query_err:
                if query_err.code != 403:
                    raise

            print(
                f"Batch add returned 403. Retrying one-by-one for {len(batch)} tracks…",
                file=sys.stderr,
                flush=True,
            )
            for uri in batch:
                try:
                    add_batch_with_query([uri])
                    added_count += 1
                except urllib.error.HTTPError as single_err:
                    if single_err.code == 403:
                        print(f"Skipping forbidden track URI: {uri}", file=sys.stderr, flush=True)
                        continue
                    raise

    return added_count


def main() -> None:
    spotify_client_id = require_env("SPOTIFY_CLIENT_ID")
    spotify_client_secret = require_env("SPOTIFY_CLIENT_SECRET")
    spotify_refresh_token = require_env("SPOTIFY_REFRESH_TOKEN")
    github_token = require_env("GITHUB_TOKEN")

    model_name = os.getenv("GITHUB_MODEL", DEFAULT_MODEL)
    model_temperature = float(os.getenv("GITHUB_MODEL_TEMPERATURE", "0.8"))
    top_tracks_limit = int(os.getenv("SPOTIFY_TOP_TRACKS_LIMIT", "15"))
    recommendation_limit = int(os.getenv("SPOTIFY_RECOMMENDATIONS_LIMIT", "30"))

    print("Authenticating with Spotify…", flush=True)
    token, granted_scopes = spotify_access_token(
        spotify_client_id,
        spotify_client_secret,
        spotify_refresh_token,
    )
    me = spotify_get_me(token)
    user_id: str = me["id"]
    user_country = str(me.get("country", "")).strip().upper() or None
    search_market = user_country

    today = dt.date.today()
    target_week = iso_week_label(today)
    source_week = iso_week_label(today - dt.timedelta(days=7))

    print(f"Authenticated as user: {user_id} ({me.get('display_name', 'N/A')})", flush=True)
    print(f"User market: {user_country or 'N/A'}", flush=True)
    print(f"Search market: {search_market or 'none'}", flush=True)
    print(f"Target week: {target_week}", flush=True)
    print(f"Source week: {source_week}", flush=True)

    can_read_private_playlists = "playlist-read-private" in granted_scopes

    existing_playlist_id: str | None = None
    if can_read_private_playlists:
        try:
            existing_target = spotify_find_playlist_by_name(token, target_week)
        except urllib.error.HTTPError as err:
            if err.code == 403:
                print(
                    "Could not read existing playlists (403). Continuing without dedupe.",
                    file=sys.stderr,
                    flush=True,
                )
                existing_target = None
                can_read_private_playlists = False
            else:
                raise
        if existing_target:
            existing_playlist_id = str(existing_target.get("id") or "")
            print(
                f"Playlist {target_week} already exists ({existing_playlist_id}). Will overwrite.",
                flush=True,
            )
    else:
        print(
            "Skipping existing-playlist check (missing playlist-read-private scope).",
            file=sys.stderr,
            flush=True,
        )

    print("Fetching top tracks and artists…", flush=True)
    current_top_tracks = spotify_get_top_tracks(token, limit=top_tracks_limit)
    current_top_artists = spotify_get_top_artists(token, limit=10)
    if len(current_top_tracks) < 5:
        print(
            f"Not enough listening history — got {len(current_top_tracks)} tracks, need at least 5.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_tracks = current_top_tracks
    source_artists = current_top_artists
    source_label = "current short-term listening"
    source_playlist_id: str | None = None

    if can_read_private_playlists:
        previous_playlist = spotify_find_playlist_by_name(token, source_week)
        if previous_playlist:
            previous_tracks = spotify_get_playlist_tracks(
                token,
                previous_playlist["id"],
                limit=max(100, recommendation_limit),
            )
            if len(previous_tracks) >= 5:
                source_tracks = previous_tracks
                source_artists = artists_from_tracks(previous_tracks, limit=10)
                source_label = f"playlist {source_week}"
                source_playlist_id = str(previous_playlist.get("id") or "") or None
                print(
                    f"Using {len(previous_tracks)} tracks from {source_label} as source data"
                    f" (id: {source_playlist_id or 'unknown'}).",
                    flush=True,
                )
            else:
                print(
                    f"Found {source_label} but it has fewer than 5 tracks; using short-term listening fallback.",
                    flush=True,
                )
        else:
            print(
                f"No playlist named {source_week} found; using short-term listening fallback.",
                flush=True,
            )
    else:
        print(
            "No previous-playlist lookup available; using short-term listening fallback.",
            flush=True,
        )

    print(
        f"Grounding source: {source_label}"
        f"{f' (id: {source_playlist_id})' if source_playlist_id else ''}.",
        flush=True,
    )

    print("Building discovery track mix (recommendations, related artists, genre search)…", flush=True)
    rec_uris = spotify_get_discovery_tracks(
        token,
        source_tracks,
        source_artists,
        current_top_artists,
        market=search_market,
    )
    if not rec_uris:
        print(
            f"No discovery tracks found from {source_label}; using source tracks as fallback.",
            file=sys.stderr,
            flush=True,
        )
        rec_uris = [track["uri"] for track in source_tracks if track.get("uri")]
        rec_uris = list(dict.fromkeys(rec_uris))

    print("Generating playlist metadata with AI…", flush=True)
    playlist_meta = model_playlist_metadata(
        github_token,
        model_name,
        source_tracks,
        model_temperature,
        source_week=source_week,
        target_week=target_week,
    )

    playlist_name = target_week
    playlist_description = playlist_meta["description"]

    if existing_playlist_id:
        print("Overwriting existing playlist…", flush=True)
        removed = spotify_clear_playlist(token, existing_playlist_id)
        print(f"  Removed {removed} existing tracks.", flush=True)
        spotify_update_playlist_details(token, existing_playlist_id, playlist_name, playlist_description)
        playlist_id = existing_playlist_id
    else:
        print("Creating playlist…", flush=True)
        try:
            playlist_id = spotify_create_playlist(token, playlist_name, playlist_description)
        except urllib.error.HTTPError as err:
            if err.code == 403:
                print(
                    "\nPlaylist creation returned 403 Forbidden.\n"
                    "Possible causes:\n"
                    "  1. Add your Spotify account email to the app's User Management\n"
                    "     at https://developer.spotify.com/dashboard (Settings → User Management)\n"
                    "  2. Re-authorise with all required scopes and update the\n"
                    "     SPOTIFY_REFRESH_TOKEN secret.",
                    file=sys.stderr,
                )
            raise
    added_count = spotify_add_tracks(token, playlist_id, rec_uris)
    if added_count == 0:
        print(
            "No source/discovery tracks could be added; falling back to current top tracks.",
            file=sys.stderr,
            flush=True,
        )
        top_track_uris = [track["uri"] for track in current_top_tracks if track.get("uri")]
        top_track_uris = list(dict.fromkeys(top_track_uris))
        added_count = spotify_add_tracks(token, playlist_id, top_track_uris)
        rec_uris = top_track_uris

    if added_count == 0:
        print("No tracks could be added to the playlist.", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"\n✓ Created playlist: {playlist_name}", flush=True)
    print(f"  Added tracks: {added_count}/{len(rec_uris)}", flush=True)
    print(f"  https://open.spotify.com/playlist/{playlist_id}", flush=True)


if __name__ == "__main__":
    main()