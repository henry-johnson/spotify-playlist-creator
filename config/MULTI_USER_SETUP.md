# Multi-User Setup Guide

This script supports multiple Spotify users creating playlists simultaneously.

## Architecture

- **Shared credentials**: One Spotify app (`SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET`) is shared across all users.
- **Per-user refresh tokens**: Each user has their own `SPOTIFY_USER_REFRESH_TOKEN_{FIRST}_{LAST}` secret.
- **Auto-discovery**: The script discovers all `SPOTIFY_USER_REFRESH_TOKEN_*` environment variables and creates a playlist for each.

## Setup Instructions

### 1. Create a Spotify App (once)

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app with redirect URI `http://127.0.0.1:8888/callback`.
3. Note the `Client ID` and `Client Secret`.
4. Under **Settings → User Management**, add every user's Spotify email address.

### 2. Generate a Refresh Token (per user)

Each user must authorise with all 5 required scopes:

```text
https://accounts.spotify.com/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&scope=user-top-read%20playlist-modify-private%20playlist-modify-public%20playlist-read-private%20ugc-image-upload
```

Exchange the authorisation code for a refresh token:

```bash
curl -X POST https://accounts.spotify.com/api/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "$SPOTIFY_CLIENT_ID:$SPOTIFY_CLIENT_SECRET" \
  -d grant_type=authorization_code \
  -d code="AUTH_CODE_FROM_REDIRECT" \
  -d redirect_uri="http://127.0.0.1:8888/callback"
```

### 3. Add GitHub Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

| Secret                                     | Value                              |
| ------------------------------------------ | ---------------------------------- |
| `OPENAI_API_KEY`                           | Your OpenAI API key (shared)       |
| `SPOTIFY_CLIENT_ID`                        | Spotify app client ID (shared)     |
| `SPOTIFY_CLIENT_SECRET`                    | Spotify app client secret (shared) |
| `SPOTIFY_USER_REFRESH_TOKEN_HENRY_JOHNSON` | Henry's refresh token              |
| `SPOTIFY_USER_REFRESH_TOKEN_PENNY_JOHNSON` | Penny's refresh token              |

> **Naming convention**: `SPOTIFY_USER_REFRESH_TOKEN_{FIRST}_{LAST}` — uppercase, underscores between names. The script converts this to a display name (e.g. `Henry Johnson`).

### 4. Update Workflow

Edit `.github/workflows/build-weekly-spotify-playlist.yml` to pass each user's secret as an env var:

```yaml
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
  SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
  SPOTIFY_USER_REFRESH_TOKEN_HENRY_JOHNSON: ${{ secrets.SPOTIFY_USER_REFRESH_TOKEN_HENRY_JOHNSON }}
  SPOTIFY_USER_REFRESH_TOKEN_PENNY_JOHNSON: ${{ secrets.SPOTIFY_USER_REFRESH_TOKEN_PENNY_JOHNSON }}
```

### How It Works

- The workflow runs every Monday at **3 AM UTC**.
- `multi_user_config.py` scans for all `SPOTIFY_USER_REFRESH_TOKEN_*` env vars.
- For each user found, it creates (or overwrites) that week's playlist independently.
- If one user fails (e.g. expired token), the script continues with the remaining users.

### Troubleshooting

| Problem                 | Solution                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------- |
| 403 on `GET /v1/me`     | Add the user's Spotify email to User Management in the developer dashboard         |
| Missing required scopes | Regenerate the refresh token with all 5 scopes                                     |
| User not found          | Check the env var name matches `SPOTIFY_USER_REFRESH_TOKEN_{FIRST}_{LAST}` exactly |
| Workflow not running    | Verify all secrets exist and the workflow is enabled under Actions settings        |
