"""Create a weekly Spotify playlist using OpenAI + Spotify API.

Orchestrator script — delegates to modular components in the same directory.
"""

from __future__ import annotations

import datetime as dt
import heapq
import os
import sys
import urllib.error
from collections import deque

from model_provider_openai import OpenAIProvider
from config import (
    OPENAI_API_BASE_URL,
    OPENAI_TEXT_MODEL_SMALL,
    require_env,
)
from multi_user_config import load_users_from_env
from artwork import generate_playlist_artwork_base64
from spotify_auth import spotify_access_token
from spotify_api import (
    artists_from_tracks,
    iso_week_label,
    spotify_add_tracks,
    spotify_clear_playlist,
    spotify_create_playlist,
    spotify_find_playlist_by_name,
    spotify_get_me,
    spotify_get_playlist_tracks,
    spotify_track_primary_artist_by_uri,
    spotify_get_top_artists,
    spotify_get_top_tracks,
    spotify_upload_playlist_cover_image,
    spotify_update_playlist_details,
)
from metadata import generate_playlist_description, assemble_final_description
from discovery import build_discovery_mix


def _spread_tracks_by_artist(
    uris: list[str],
    primary_artist_by_uri: dict[str, str],
) -> list[str]:
    """Reorder URIs to reduce adjacent tracks by the same primary artist."""
    buckets: dict[str, deque[str]] = {}
    for uri in uris:
        artist_key = primary_artist_by_uri.get(uri, "") or ""
        if artist_key not in buckets:
            buckets[artist_key] = deque()
        buckets[artist_key].append(uri)

    heap: list[tuple[int, str]] = [
        (-len(bucket), artist_key)
        for artist_key, bucket in buckets.items()
        if bucket
    ]
    heapq.heapify(heap)

    ordered: list[str] = []
    previous_artist = ""

    while heap:
        count1, artist1 = heapq.heappop(heap)
        if artist1 == previous_artist and heap:
            count2, artist2 = heapq.heappop(heap)
            ordered.append(buckets[artist2].popleft())
            previous_artist = artist2
            count2 += 1
            if count2 < 0:
                heapq.heappush(heap, (count2, artist2))
            heapq.heappush(heap, (count1, artist1))
            continue

        ordered.append(buckets[artist1].popleft())
        previous_artist = artist1
        count1 += 1
        if count1 < 0:
            heapq.heappush(heap, (count1, artist1))

    return ordered


def create_playlist_for_user(
    username: str,
    spotify_client_id: str,
    spotify_client_secret: str,
    spotify_refresh_token: str,
    provider: OpenAIProvider,
    *,
    model_temperature: float = 0.7,
    recommendations_temperature: float = 1.0,
    artwork_enabled: bool = True,
    top_tracks_limit: int = 15,
    recommendation_limit: int = 30,
) -> None:
    """Create a weekly playlist for a single user."""
    print(f"\n{'='*60}", flush=True)
    print(f"Creating playlist for: {username}", flush=True)
    print(f"{'='*60}", flush=True)
    
    # ── Authenticate ────────────────────────────────────────────────
    print("Authenticating with Spotify…", flush=True)
    token, granted_scopes = spotify_access_token(
        spotify_client_id, spotify_client_secret, spotify_refresh_token,
    )
    me = spotify_get_me(token)
    user_id: str = me["id"]
    display_name = str(me.get("display_name") or "").strip()
    profile_first_name = display_name.split()[0] if display_name else "there"
    user_country = str(me.get("country", "")).strip().upper() or None
    search_market = user_country

    today = dt.date.today()
    target_week = iso_week_label(today)
    source_week = iso_week_label(today - dt.timedelta(days=7))

    print(
        f"Authenticated as user: {user_id} "
        f"({me.get('display_name', 'N/A')})",
        flush=True,
    )
    print(f"User market: {user_country or 'N/A'}", flush=True)
    print(f"Search market: {search_market or 'none'}", flush=True)
    print(f"Target week: {target_week}", flush=True)
    print(f"Source week: {source_week}", flush=True)
    print(f"Description model: {model_name}", flush=True)
    print(f"Recommendations model: {recommendations_model}", flush=True)
    print(
        f"Artwork: {'enabled' if artwork_enabled else 'disabled'}"
        f" (model: {artwork_model})",
        flush=True,
    )

    # ── Check for existing playlist ─────────────────────────────────
    can_read_private = "playlist-read-private" in granted_scopes

    existing_playlist_id: str | None = None
    if can_read_private:
        try:
            existing_target = spotify_find_playlist_by_name(
                token,
                target_week,
                owner_id=user_id,
            )
        except urllib.error.HTTPError as err:
            if err.code in (403, 429):
                print(
                    "Could not read existing playlists "
                    f"({err.code}). Continuing without dedupe.",
                    file=sys.stderr,
                    flush=True,
                )
                existing_target = None
                can_read_private = False
            else:
                raise
        if existing_target:
            existing_playlist_id = str(existing_target.get("id") or "")
            print(
                f"Playlist {target_week} already exists "
                f"({existing_playlist_id}). Will overwrite.",
                flush=True,
            )
    else:
        print(
            "Skipping existing-playlist check "
            "(missing playlist-read-private scope).",
            file=sys.stderr,
            flush=True,
        )

    # ── Gather source data ──────────────────────────────────────────
    print("Fetching top tracks and artists…", flush=True)
    current_top_tracks = spotify_get_top_tracks(token, limit=top_tracks_limit)
    current_top_artists = spotify_get_top_artists(token, limit=10)
    if len(current_top_tracks) < 5:
        print(
            f"Not enough listening history — got {len(current_top_tracks)} "
            "tracks, need at least 5.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_tracks = current_top_tracks
    source_artists = current_top_artists
    source_label = "current short-term listening"
    source_playlist_id: str | None = None

    if can_read_private:
        try:
            previous_playlist = spotify_find_playlist_by_name(
                token,
                source_week,
                owner_id=user_id,
            )
        except urllib.error.HTTPError as err:
            if err.code in (403, 429):
                print(
                    f"Could not read previous playlists ({err.code}); "
                    "using short-term listening fallback.",
                    file=sys.stderr,
                    flush=True,
                )
                previous_playlist = None
            else:
                raise
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
                source_playlist_id = (
                    str(previous_playlist.get("id") or "") or None
                )
                print(
                    f"Using {len(previous_tracks)} tracks from {source_label}"
                    f" as source data (id: {source_playlist_id or 'unknown'}).",
                    flush=True,
                )
            else:
                print(
                    f"Found {source_label} but it has fewer than 5 tracks; "
                    "using short-term listening fallback.",
                    flush=True,
                )
        else:
            print(
                f"No playlist named {source_week} found; "
                "using short-term listening fallback.",
                flush=True,
            )
    else:
        print(
            "No previous-playlist lookup available; "
            "using short-term listening fallback.",
            flush=True,
        )

    print(
        f"Grounding source: {source_label}"
        f"{f' (id: {source_playlist_id})' if source_playlist_id else ''}.",
        flush=True,
    )

    # ── Build discovery mix ─────────────────────────────────────────
    print("Building discovery track mix…", flush=True)
    try:
        rec_uris = build_discovery_mix(
            spotify_token=token,
            provider=provider,
            source_tracks=source_tracks,
            source_artists=source_artists,
            current_top_artists=current_top_artists,
            source_week=source_week,
            target_week=target_week,
            market=search_market,
            temperature=recommendations_temperature,
        )
    except Exception as err:
        print(
            f"⚠ Discovery mix failed (rate limit?): {err}",
            file=sys.stderr,
            flush=True,
        )
        rec_uris = []
    
    if not rec_uris:
        print(
            f"No discovery tracks from {source_label}; "
            "using source tracks as fallback.",
            file=sys.stderr,
            flush=True,
        )
        rec_uris = [
            track["uri"] for track in source_tracks if track.get("uri")
        ]
        rec_uris = list(dict.fromkeys(rec_uris))

    # ── Generate playlist description ───────────────────────────────
    print("Generating playlist description with AI…", flush=True)
    playlist_description = generate_playlist_description(
        provider,
        source_tracks,
        model_temperature,
        source_week=source_week,
        target_week=target_week,
        listener_first_name=profile_first_name,
    )

    # Prepend credits/timestamp prefix and truncate to Spotify's limit
    playlist_description = assemble_final_description(playlist_description)

    # ── Create or overwrite playlist ────────────────────────────────
    playlist_name = target_week

    if existing_playlist_id:
        print("Overwriting existing playlist…", flush=True)
        removed = spotify_clear_playlist(token, existing_playlist_id)
        print(f"  Removed {removed} existing tracks.", flush=True)
        spotify_update_playlist_details(
            token, existing_playlist_id, playlist_name, playlist_description,
        )
        playlist_id = existing_playlist_id
    else:
        print("Creating playlist…", flush=True)
        try:
            playlist_id = spotify_create_playlist(
                token, playlist_name, playlist_description,
            )
        except urllib.error.HTTPError as err:
            if err.code == 403:
                print(
                    "\nPlaylist creation returned 403 Forbidden.\n"
                    "Possible causes:\n"
                    "  1. Add your Spotify account email to the app's "
                    "User Management\n"
                    "     at https://developer.spotify.com/dashboard "
                    "(Settings → User Management)\n"
                    "  2. Re-authorise with all required scopes and "
                    "update the\n"
                    "     SPOTIFY_REFRESH_TOKEN secret.",
                    file=sys.stderr,
                )
            raise

    # ── Add tracks (final dedupe) ────────────────────────────────────
    seen: set[str] = set()
    unique_uris: list[str] = []
    for uri in rec_uris:
        if uri not in seen:
            seen.add(uri)
            unique_uris.append(uri)
    rec_uris = unique_uris[:100]

    primary_artist_by_uri = spotify_track_primary_artist_by_uri(token, rec_uris)
    if primary_artist_by_uri:
        rec_uris = _spread_tracks_by_artist(rec_uris, primary_artist_by_uri)

    added_count = spotify_add_tracks(token, playlist_id, rec_uris)
    if added_count == 0:
        print(
            "No source/discovery tracks could be added; "
            "falling back to current top tracks.",
            file=sys.stderr,
            flush=True,
        )
        top_track_uris = [
            track["uri"]
            for track in current_top_tracks
            if track.get("uri")
        ]
        top_track_uris = list(dict.fromkeys(top_track_uris))
        added_count = spotify_add_tracks(token, playlist_id, top_track_uris)
        rec_uris = top_track_uris

    if added_count == 0:
        print(
            "No tracks could be added to the playlist.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    # ── Generate/upload playlist artwork (optional) ────────────────
    if artwork_enabled:
        if "ugc-image-upload" not in granted_scopes:
            print(
                "Skipping artwork upload "
                "(missing optional scope: ugc-image-upload).",
                file=sys.stderr,
                flush=True,
            )
        else:
            print("Generating playlist artwork with AI…", flush=True)
            try:
                artwork_b64 = generate_playlist_artwork_base64(
                    provider,
                    source_tracks,
                    source_artists,
                    source_week=source_week,
                    target_week=target_week,
                )
                if artwork_b64:
                    try:
                        spotify_upload_playlist_cover_image(
                            token,
                            playlist_id,
                            artwork_b64,
                        )
                        print("  Uploaded custom playlist artwork.", flush=True)
                    except urllib.error.HTTPError as err:
                        if err.code == 403:
                            print(
                                "  Artwork upload forbidden (403). "
                                "Check ownership and ugc-image-upload scope.",
                                file=sys.stderr,
                                flush=True,
                            )
                        elif err.code == 429:
                            print(
                                "  Artwork upload rate limited (429). "
                                "Skipping for now.",
                                file=sys.stderr,
                                flush=True,
                            )
                        else:
                            print(
                                f"  Artwork upload failed ({err}).",
                                file=sys.stderr,
                                flush=True,
                            )
                else:
                    print(
                        "  Artwork generation skipped or failed.",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as err:
                print(
                    f"  ⚠ Artwork generation failed (rate limit?): {err}",
                    file=sys.stderr,
                    flush=True,
                )

    print(f"\n✓ Created playlist: {playlist_name}", flush=True)
    print(f"  Added tracks: {added_count}/{len(rec_uris)}", flush=True)
    print(
        f"  https://open.spotify.com/playlist/{playlist_id}",
        flush=True,
    )


def main() -> None:
    """Main entry point: load OpenAI config and run for all users."""
    # ── Global config ───────────────────────────────────────────────
    openai_api_key = require_env("OPENAI_API_KEY")
    
    model_temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
    recommendations_temperature = float(os.getenv("OPENAI_RECOMMENDATIONS_TEMPERATURE", "1.0"))
    artwork_enabled = os.getenv("ENABLE_PLAYLIST_ARTWORK", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    top_tracks_limit = int(os.getenv("SPOTIFY_TOP_TRACKS_LIMIT", "15"))
    recommendation_limit = int(os.getenv("SPOTIFY_RECOMMENDATIONS_LIMIT", "30"))

    # ── Initialize OpenAI Provider ──────────────────────────────────
    provider = OpenAIProvider(api_key=openai_api_key, base_url=OPENAI_API_BASE_URL)
    
    # ── Load users from environment ─────────────────────────────────
    users = load_users_from_env()
    
    if not users:
        print(
            "No users found. Set SPOTIFY_USER_* environment variables.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    
    print(f"Found {len(users)} user(s): {', '.join(u.username for u in users)}")
    print()
    
    # ── Create playlists for each user ──────────────────────────────
    for user in users:
        try:
            create_playlist_for_user(
                username=user.username,
                spotify_client_id=user.spotify_client_id,
                spotify_client_secret=user.spotify_client_secret,
                spotify_refresh_token=user.spotify_refresh_token,
                provider=provider,
                model_temperature=model_temperature,
                recommendations_temperature=recommendations_temperature,
                artwork_enabled=artwork_enabled,
                top_tracks_limit=top_tracks_limit,
                recommendation_limit=recommendation_limit,
            )
        except Exception as exc:
            print(
                f"❌ Playlist creation failed for {user.username}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*60}")
    print("✓ Playlist creation complete for all users")


if __name__ == "__main__":
    main()
