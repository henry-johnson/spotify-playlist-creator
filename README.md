# spotify-playlist-creator

Automate a **weekly Spotify playlist** using:

- **Spotify Web API** for listening data + playlist creation
- **GitHub Models** for playlist title/description generation
- **GitHub Actions** for scheduling

## What this repo does

Every Monday (or on manual trigger), GitHub Actions runs `scripts/create_weekly_playlist.py` to:

1. Refresh your Spotify access token.
2. Build the target playlist week name (for example `2026-W08`) and skip if it already exists.
3. Load source data from the previous week playlist (for example `2026-W07`) when available.
4. Fall back to your `short_term` top tracks/artists when a previous week playlist does not exist.
5. Search Spotify for discovery tracks by genre/artist.
6. Ask GitHub Models for a grounded playlist description.
7. Create the target week private playlist and add tracks.

## 1) Create a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app.
3. Add a Redirect URI (for example: `http://127.0.0.1:8888/callback`).
4. Save these values:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`

## 2) Generate a Spotify refresh token (one-time)

Required scopes: `user-top-read playlist-modify-private playlist-modify-public`.

Optional scope (recommended): `playlist-read-private`.

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
- `SPOTIFY_RECOMMENDATIONS_LIMIT` (default `30`) — max discovery tracks to add

Prompt customization:

- Edit `prompts/playlist_user_prompt.md` to customize playlist generation. The file supports placeholders `{source_week}`, `{target_week}`, `{top_artists}`, and `{top_tracks}`.

> The workflow uses `secrets.GITHUB_TOKEN` and requests `models: read` permission for GitHub Models.

## 4) Run the workflow

- Manual: **Actions → Weekly Spotify Playlist → Run workflow**
- Scheduled: Every Monday at `03:00 UTC` (3 AM GMT / 4 AM BST) (`cron: 0 3 * * 1`)

## Files

- `.github/workflows/weekly_playlist.yml` — scheduler and job definition.
- `scripts/create_weekly_playlist.py` — Spotify + GitHub Models integration logic.
- `prompts/playlist_user_prompt.md` — default user prompt template.

## Notes

- The script creates **one private playlist per ISO week** (for example `2026-W08`) when `playlist-read-private` is granted; without it, duplicate-week detection is skipped.
- Week `W08` is grounded on playlist data from `W07` when available and readable.
- On first run (or if `W07` is missing), it falls back to your current `short_term` listening data.
- If your account has too little listening history, Spotify may return fewer recommendations.
- Set your preferred genres directly in the prompt file/template (for example in `prompts/playlist_user_prompt.md`) so the model pulls genre guidance from prompt content.
