# build-weekly-spotify-playlist

Automate a **weekly Spotify playlist** using:

- **Spotify Web API** for listening data + playlist creation
- **GitHub Models** for playlist title/description generation
- **GitHub Actions** for scheduling

## What this repo does

Every Monday (or on manual trigger), GitHub Actions runs `scripts/create_weekly_playlist.py` to:

1. Refresh your Spotify access token.
2. Build the target playlist week name (for example `2026-W08`).
3. If `playlist-read-private` is granted, check whether that week's playlist already exists — if it does, **overwrite it** (clear tracks and update metadata) rather than creating a new one.
4. If `playlist-read-private` is granted, load source data from the previous week playlist (for example `2026-W07`).
5. Fall back to your `short_term` top tracks/artists when previous week playlist data is unavailable.
6. Build a discovery track mix:
   - **Familiar anchors** — shuffled source week tracks (up to 10)
   - **Genre/artist search** (`GET /v1/search`) to fill remaining slots to ~28 tracks total
7. Ask GitHub Models for a grounded playlist description.
8. Create (or overwrite) the target week private playlist and add the discovery mix.

## 1) Create a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app.
3. Add a Redirect URI (for example: `http://127.0.0.1:8888/callback`).
4. Save these values:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`

## 2) Generate a Spotify refresh token (one-time)

Required scopes: `user-top-read playlist-modify-private playlist-modify-public`.

**Strongly recommended scope: `playlist-read-private`.** Without it, the script cannot detect an existing week playlist and will create a duplicate every run instead of overwriting.

Example authorization URL:

```text
https://accounts.spotify.com/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&scope=user-top-read%20playlist-modify-private%20playlist-modify-public%20playlist-read-private
```

After approving, Spotify redirects with a `code=...` query param. Exchange it:

```bash
curl -X POST https://accounts.spotify.com/api/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "$SPOTIFY_CLIENT_ID:$SPOTIFY_CLIENT_SECRET" \
  -d grant_type=authorization_code \
  -d code="YOUR_CODE" \
  -d redirect_uri="http://127.0.0.1:8888/callback"
```

Copy `refresh_token` from the response and store it as `SPOTIFY_REFRESH_TOKEN` in GitHub secrets.

## 3) Configure GitHub repo settings

Set these repository **Secrets**:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REFRESH_TOKEN`

Optional repository **Variables**:

- `GITHUB_MODEL` (default `gpt-4o-mini`)
- `GITHUB_MODEL_TEMPERATURE` (default `0.8`)
- `SPOTIFY_TOP_TRACKS_LIMIT` (default `15`)
- `SPOTIFY_RECOMMENDATIONS_LIMIT` (default `30`) — max tracks fetched from a previous week playlist when grounding source data

Prompt customization:

- Edit `prompts/playlist_user_prompt.md` to customize playlist generation. The file supports placeholders `{source_week}`, `{target_week}`, `{top_artists}`, and `{top_tracks}`.

> The workflow uses `secrets.GITHUB_TOKEN` and requests `models: read` permission for GitHub Models.

## 4) Run the workflow

- Manual: **Actions → Build Weekly Spotify Playlist → Run workflow**
- Scheduled: Every Monday at `03:00 UTC` (3 AM GMT / 4 AM BST) (`cron: 0 3 * * 1`)

## Files

- `.github/workflows/build-weekly-spotify-playlist.yml` — scheduler and job definition.
- `scripts/create_weekly_playlist.py` — Spotify + GitHub Models integration logic.
- `prompts/playlist_user_prompt.md` — default user prompt template.

## Notes

- The script creates **one private playlist per ISO week** (for example `2026-W08`) when `playlist-read-private` is granted. If that playlist already exists, the script **overwrites it** — it clears all existing tracks, updates the description with freshly generated AI copy, then repopulates with a new discovery mix. Without `playlist-read-private`, overwrite detection is skipped and a new playlist is created each run, resulting in duplicates.
- The discovery mix targets ~28 tracks per week: up to 10 familiar anchors from the source week, then genre and artist name searches to fill remaining slots.
- Week `W08` is grounded on playlist data from `W07` when available and readable. On first run (or if `W07` is missing), it falls back to your current `short_term` listening data.
- Playlist descriptions are automatically normalized and truncated to Spotify's limit before creation.
- If your account has too little listening history (fewer than 5 top tracks), the script exits early.
- Set your preferred genres or tone directly in `prompts/playlist_user_prompt.md` — the prompt supports placeholders `{source_week}`, `{target_week}`, `{top_artists}`, and `{top_tracks}`.
