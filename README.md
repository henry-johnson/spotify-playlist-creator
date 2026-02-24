# spotify-playlist-creator

Automate a **weekly Spotify playlist** using:

- **Spotify Web API** for listening data + playlist creation
- **GitHub Models** for playlist title/description generation
- **GitHub Actions** for scheduling

## What this repo does

Every Monday (or on manual trigger), GitHub Actions runs `scripts/create_weekly_playlist.py` to:

1. Refresh your Spotify access token.
2. Pull your top tracks (`short_term`).
3. Find your top artists and extract their genres.
4. Search Spotify for discovery tracks by genre.
5. Ask GitHub Models for a playlist description.
6. Create a new private playlist and add the discovery tracks.

## 1) Create a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app.
3. Add a Redirect URI (for example: `http://127.0.0.1:8888/callback`).
4. Save these values:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`

## 2) Generate a Spotify refresh token (one-time)

You need scopes: `user-top-read playlist-modify-private`.

Example authorization URL:

```text
https://accounts.spotify.com/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&scope=user-top-read%20playlist-modify-private
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

- `GITHUB_MODEL` (default `gpt-5-mini`)
- `GITHUB_MODEL_TEMPERATURE` (default `0.8`)
- `SPOTIFY_TOP_TRACKS_LIMIT` (default `15`)
- `SPOTIFY_RECOMMENDATIONS_LIMIT` (default `30`) — max discovery tracks to add

Prompt customization:

- Edit `prompts/playlist_user_prompt.md` to customize playlist generation. The file supports placeholders `{top_artists}` and `{top_tracks}`.

> The workflow uses `secrets.GITHUB_TOKEN` and requests `models: read` permission for GitHub Models.

## 4) Run the workflow

- Manual: **Actions → Weekly Spotify Playlist → Run workflow**
- Scheduled: Every Monday at `03:00 UTC` (3 AM GMT / 4 AM BST) (`cron: 0 3 * * 1`)

## Files

- `.github/workflows/weekly_playlist.yml` — scheduler and job definition.
- `scripts/create_weekly_playlist.py` — Spotify + GitHub Models integration logic.
- `prompts/playlist_user_prompt.md` — default user prompt template.

## Notes

- The script creates a **new private playlist each week**.
- If your account has too little listening history, Spotify may return fewer recommendations.
- Set your preferred genres directly in the prompt file/template (for example in `prompts/playlist_user_prompt.md`) so the model pulls genre guidance from prompt content.
