# build-weekly-spotify-playlist

Automate a **weekly Spotify playlist** using:

- **Spotify Web API** for listening data + playlist creation
- **OpenAI API** for AI-powered music discovery and playlist descriptions
- **GitHub Actions** for scheduling

## What this repo does

Every Monday (or on manual trigger), GitHub Actions runs `scripts/create_weekly_playlist.py` to:

1. Refresh each user's Spotify access token (all 5 scopes required).
2. Build the target playlist week name (for example `2026-W09`).
3. Check whether that week's playlist already exists — if it does, **overwrite it** (clear tracks and update metadata) rather than creating a new one.
4. Load source data from the previous week's playlist (for example `2026-W08`).
5. Fall back to your `short_term` top tracks/artists when previous week playlist data is unavailable.
6. Build a discovery track mix using the **AI recommendation engine**:
   - Sends your listening profile (tracks, artists, genres) to OpenAI (`gpt-5.2`)
   - The LLM acts as a music curator, generating up to 30 Spotify search queries
   - Executes those queries against Spotify search, excluding tracks you already know
   - Fills remaining slots with familiar anchors and genre/artist search fallback
   - Falls back gracefully to genre/artist search if the AI engine is unavailable
7. Ask OpenAI (`gpt-5.2`) for a grounded playlist description.
8. Create (or overwrite) the target week private playlist and add the discovery mix.
9. Optionally generate AI playlist artwork and upload it to Spotify.

## 1) Create a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app.
3. Add a Redirect URI (for example: `http://127.0.0.1:8888/callback`).
4. Save these values:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`

## 2) Generate a Spotify refresh token (one-time)

Required scopes:

- `user-top-read`
- `playlist-modify-private`
- `playlist-modify-public`
- `playlist-read-private`
- `ugc-image-upload`

Example authorization URL:

```text
https://accounts.spotify.com/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&scope=user-top-read%20playlist-modify-private%20playlist-modify-public%20playlist-read-private%20ugc-image-upload
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

| Secret                                     | Purpose                                                       |
| ------------------------------------------ | ------------------------------------------------------------- |
| `OPENAI_API_KEY`                           | OpenAI API key for descriptions, recommendations, and artwork |
| `SPOTIFY_CLIENT_ID`                        | Shared Spotify app client ID                                  |
| `SPOTIFY_CLIENT_SECRET`                    | Shared Spotify app client secret                              |
| `SPOTIFY_USER_REFRESH_TOKEN_HENRY_JOHNSON` | Per-user refresh token (repeat for each user)                 |

> Per-user secret naming convention: `SPOTIFY_USER_REFRESH_TOKEN_{FIRST}_{LAST}` (uppercase, underscores). The script auto-discovers all `SPOTIFY_USER_REFRESH_TOKEN_*` environment variables and creates a playlist for each user.

Optional repository **Variables** (environment overrides):

| Variable                        | Default | Purpose                                            |
| ------------------------------- | ------- | -------------------------------------------------- |
| `SPOTIFY_TOP_TRACKS_LIMIT`      | `15`    | Number of top tracks to fetch per user             |
| `SPOTIFY_RECOMMENDATIONS_LIMIT` | `30`    | Max tracks fetched from a previous week playlist   |
| `ENABLE_PLAYLIST_ARTWORK`       | `1`     | Set to `0` to disable AI artwork generation/upload |

> Model names and temperatures are configured in `scripts/config.py` — no env var overrides needed.

Prompt customization:

- Edit `prompts/playlist_description_prompt.md` to customize playlist descriptions. Placeholders: `{first_name}`, `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`.
- Edit `prompts/recommendations_prompt.md` to customize the AI discovery strategy. Placeholders: `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`, `{genres}`, `{max_queries}`.
- Edit `prompts/playlist_artwork_prompt.md` to customize artwork generation. Placeholders (optional): `{playlist_name}`, `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`.

## 4) Run the workflow

- Manual: **Actions → Build Weekly Spotify Playlist → Run workflow**
- Scheduled: Every Monday at `03:00 UTC` (3 AM GMT / 4 AM BST) (`cron: 0 3 * * 1`)

## Files

### Workflow

- `.github/workflows/build-weekly-spotify-playlist.yml` — scheduler and job definition.

### Scripts (modular)

| File                                | Purpose                                                                                                                |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `scripts/create_weekly_playlist.py` | Thin orchestrator — wires modules together and runs the end-to-end flow.                                               |
| `scripts/config.py`                 | Shared constants (API base URLs, models, temperatures) and environment helpers.                                        |
| `scripts/http_client.py`            | `http_json()` — stdlib HTTP client with automatic retry on 429 / 5xx.                                                  |
| `scripts/spotify_auth.py`           | Spotify OAuth token refresh and scope validation.                                                                      |
| `scripts/spotify_api.py`            | All Spotify Web API helpers (profile, top items, search, playlist CRUD).                                               |
| `scripts/multi_user_config.py`      | Auto-discovers `SPOTIFY_USER_REFRESH_TOKEN_*` env vars and loads per-user credentials.                                 |
| `scripts/model_provider.py`         | Abstract `AIProvider` interface for pluggable LLM/image backends.                                                      |
| `scripts/model_provider_openai.py`  | OpenAI API implementation of `AIProvider` (text + image generation).                                                   |
| `scripts/metadata.py`               | AI playlist description generation via OpenAI (`gpt-5.2`).                                                             |
| `scripts/recommendations.py`        | AI recommendation engine — sends listening data to `gpt-5.2` and gets back Spotify search queries for music discovery. |
| `scripts/artwork.py`                | AI playlist artwork generation (OpenAI image model) with Pillow text overlay and Spotify upload payload handling.      |
| `scripts/discovery.py`              | Track mix builder: combines AI recommendations, familiar anchors, and genre/artist search into a ~100-track playlist.  |

### Prompts

| File                                     | Placeholders                                                                                   | Used by                                  |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `prompts/playlist_description_prompt.md` | `{first_name}`, `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`              | `metadata.py` — playlist descriptions    |
| `prompts/recommendations_prompt.md`      | `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`, `{genres}`, `{max_queries}` | `recommendations.py` — discovery queries |
| `prompts/playlist_artwork_prompt.md`     | (none — self-contained seasonal prompt)                                                        | `artwork.py` — playlist cover generation |

## How the AI recommendation engine works

`scripts/recommendations.py` replaces Spotify’s restricted `/v1/recommendations` endpoint (which requires Extended Quota Mode) with a custom GPT-powered alternative:

1. **Profile assembly** — Your top tracks (with artist attribution), top artists (with Spotify genre tags), and aggregated genres are formatted into a rich prompt.
2. **LLM query generation** — The profile is sent to the OpenAI API (`gpt-5.2` by default) with a system prompt instructing it to act as a music discovery engine. It returns up to 30 Spotify search queries designed for discovery:
   - 4–5 queries for artists **similar to but different from** your current rotation
   - 3–4 genre-adjacent or cross-genre queries
   - 2–3 specific tracks or albums you’d likely enjoy
   - 2–3 left-field picks — surprising but defensible based on your pattern
3. **Search execution** — Each query is run against `GET /v1/search` (standard Spotify quota, always works).
4. **Mix assembly** — The discovery engine (`scripts/discovery.py`) combines three slots:
   - **Slot 1** (target 50): AI-recommended tracks from the search queries above
   - **Slot 2** (up to 15): Familiar anchors — shuffled tracks from the source week
   - **Slot 3** (fill to 100): Genre and artist name search fallback
5. **Deduplication** — Tracks from the source week are excluded from discovery slots. The AI engine and each search slot degrade gracefully under rate limiting.

## Notes

- The script creates **one private playlist per ISO week** (e.g. `2026-W09`) for each configured user. If that week’s playlist already exists, it **overwrites it** — clears all existing tracks, updates the description, then repopulates with a fresh discovery mix.
- The discovery mix targets ~100 tracks per week: up to 50 AI-recommended, up to 15 familiar anchors, and the rest from genre/artist search.
- Each week is grounded on the previous week’s playlist data when available. On first run (or if the previous week is missing), it falls back to your current `short_term` listening data.
- Playlist descriptions are automatically normalized and truncated to Spotify’s 300-character limit.
- If a user’s account has too little listening history (fewer than 5 top tracks), that user is skipped.
- If one user fails (e.g. expired token), the script continues with the remaining users.
- All 5 Spotify scopes are required. The script exits immediately if any are missing from a user’s token.
- Models and temperatures are configured in `scripts/config.py`. Prompts are in `prompts/`.
- **Dependencies**: Python 3.12 stdlib + Pillow (installed by the workflow). Requires `OPENAI_API_KEY`.
