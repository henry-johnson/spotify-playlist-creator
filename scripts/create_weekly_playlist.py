"""Create a weekly Spotify playlist using GitHub Models + Spotify API.

Orchestrator script — delegates to modular components in the same directory.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import urllib.error

from config import DEFAULT_MODEL, DEFAULT_RECOMMENDATIONS_MODEL, require_env
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
    spotify_get_top_artists,
    spotify_get_top_tracks,
    spotify_update_playlist_details,
)
from ai_metadata import generate_playlist_description
from discovery import build_discovery_mix


def main() -> None:
    # ── Environment ─────────────────────────────────────────────────
    spotify_client_id = require_env("SPOTIFY_CLIENT_ID")
    spotify_client_secret = require_env("SPOTIFY_CLIENT_SECRET")
    spotify_refresh_token = require_env("SPOTIFY_REFRESH_TOKEN")
    github_token = require_env("GITHUB_TOKEN")

    model_name = os.getenv("GITHUB_MODEL", DEFAULT_MODEL)
    recommendations_model = os.getenv(
        "GITHUB_RECOMMENDATIONS_MODEL", DEFAULT_RECOMMENDATIONS_MODEL,
    )
    model_temperature = float(os.getenv("GITHUB_MODEL_TEMPERATURE", "0.8"))
    recommendations_temperature = float(
        os.getenv("GITHUB_RECOMMENDATIONS_TEMPERATURE", "1.0"),
    )
    top_tracks_limit = int(os.getenv("SPOTIFY_TOP_TRACKS_LIMIT", "15"))
    recommendation_limit = int(os.getenv("SPOTIFY_RECOMMENDATIONS_LIMIT", "30"))

    # ── Authenticate ────────────────────────────────────────────────
    print("Authenticating with Spotify…", flush=True)
    token, granted_scopes = spotify_access_token(
        spotify_client_id, spotify_client_secret, spotify_refresh_token,
    )
    me = spotify_get_me(token)
    user_id: str = me["id"]
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

    # ── Check for existing playlist ─────────────────────────────────
    can_read_private = "playlist-read-private" in granted_scopes

    existing_playlist_id: str | None = None
    if can_read_private:
        try:
            existing_target = spotify_find_playlist_by_name(token, target_week)
        except urllib.error.HTTPError as err:
            if err.code == 403:
                print(
                    "Could not read existing playlists (403). "
                    "Continuing without dedupe.",
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
    rec_uris = build_discovery_mix(
        spotify_token=token,
        gh_token=github_token,
        recommendations_model=recommendations_model,
        source_tracks=source_tracks,
        source_artists=source_artists,
        current_top_artists=current_top_artists,
        source_week=source_week,
        target_week=target_week,
        market=search_market,
        temperature=recommendations_temperature,
    )
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
        github_token,
        model_name,
        source_tracks,
        model_temperature,
        source_week=source_week,
        target_week=target_week,
    )

    # Prepend a human-readable creation timestamp
    created_at = dt.datetime.now(dt.timezone.utc).strftime(
        "%b %d, %Y at %I:%M:%S %p UTC",
    )
    playlist_description = f"Created: {created_at} \u2014 {playlist_description}"

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

    print(f"\n✓ Created playlist: {playlist_name}", flush=True)
    print(f"  Added tracks: {added_count}/{len(rec_uris)}", flush=True)
    print(
        f"  https://open.spotify.com/playlist/{playlist_id}",
        flush=True,
    )


if __name__ == "__main__":
    main()
