# build-weekly-spotify-playlist

Automate a **weekly Spotify playlist** using:

- **Spotify Web API** for listening data + playlist creation
- **GitHub Models** for AI-powered music discovery and playlist descriptions
- **GitHub Actions** for scheduling

## What this repo does

Every Monday (or on manual trigger), GitHub Actions runs `scripts/create_weekly_playlist.py` to:

1. Refresh your Spotify access token.
2. Build the target playlist week name (for example `2026-W08`).
3. If `playlist-read-private` is granted, check whether that week's playlist already exists — if it does, **overwrite it** (clear tracks and update metadata) rather than creating a new one.
4. If `playlist-read-private` is granted, load source data from the previous week playlist (for example `2026-W07`).
5. Fall back to your `short_term` top tracks/artists when previous week playlist data is unavailable.
6. Build a discovery track mix using the **AI recommendation engine**:
   - Sends your listening profile (tracks, artists, genres) to GitHub Models
   - The LLM acts as a music curator, generating 15 diverse Spotify search queries across 7 strategies: adjacent genres, similar (lesser-known) artists, era exploration, mood crossovers, deep cuts, genre blends, and new releases
   - Executes those queries against Spotify search and scores results for novelty (penalising tracks/artists you already know)
   - Fills remaining slots with familiar anchors and genre/artist search fallback
   - Falls back entirely to basic genre/artist search if the AI engine is unavailable
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

- `GITHUB_MODEL` (default `gpt-4o-mini`) — model used for playlist descriptions
- `GITHUB_MODEL_TEMPERATURE` (default `0.8`) — temperature for description generation
- `GITHUB_RECOMMENDATIONS_MODEL` (default `gpt-4o`) — model used for the AI recommendation engine (try `gpt-5` if you have access)
- `GITHUB_RECOMMENDATIONS_TEMPERATURE` (default `1.0`) — temperature for recommendation generation (higher = more creative)
- `SPOTIFY_TOP_TRACKS_LIMIT` (default `15`)
- `SPOTIFY_RECOMMENDATIONS_LIMIT` (default `30`) — max tracks fetched from a previous week playlist when grounding source data

Prompt customization:

- Edit `prompts/playlist_user_prompt.md` to customize playlist descriptions. Placeholders: `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`.
- Edit `prompts/recommendations_prompt.md` to customize the AI discovery strategy. Placeholders: `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`, `{genres}`, `{max_queries}`.

> The workflow uses `secrets.GITHUB_TOKEN` and requests `models: read` permission for GitHub Models.

## 4) Run the workflow

- Manual: **Actions → Build Weekly Spotify Playlist → Run workflow**
- Scheduled: Every Monday at `03:00 UTC` (3 AM GMT / 4 AM BST) (`cron: 0 3 * * 1`)

## Files

### Workflow

- `.github/workflows/build-weekly-spotify-playlist.yml` — scheduler and job definition.

### Scripts (modular)

| File | Purpose |
|---|---|
| `scripts/create_weekly_playlist.py` | Thin orchestrator — wires modules together and runs the end-to-end flow. |
| `scripts/config.py` | Shared constants (API base URLs, defaults) and environment helpers. |
| `scripts/http_client.py` | `http_json()` — stdlib HTTP client with automatic retry on 429 / 5xx. |
| `scripts/spotify_auth.py` | Spotify OAuth token refresh and scope validation. |
| `scripts/spotify_api.py` | All Spotify Web API helpers (profile, top items, search, playlist CRUD). |
| `scripts/ai_metadata.py` | AI playlist description generation via GitHub Models. |
| `scripts/ai_recommendations.py` | AI recommendation engine — sends listening data to a GPT model and gets back Spotify search queries for music discovery. |
| `scripts/discovery.py` | Track mix builder: combines AI recommendations, familiar anchors, and genre/artist search into a ~28-track playlist. |

### Prompts

| File | Placeholders | Used by |
|---|---|---|
| `prompts/playlist_user_prompt.md` | `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}` | `ai_metadata.py` — playlist descriptions |
| `prompts/recommendations_prompt.md` | `{source_week}`, `{target_week}`, `{top_artists}`, `{top_tracks}`, `{genres}`, `{max_queries}` | `ai_recommendations.py` — discovery queries |

## How the AI recommendation engine works

`scripts/ai_recommendations.py` replaces Spotify’s restricted `/v1/recommendations` endpoint (which requires Extended Quota Mode) with a custom GPT-powered alternative:

1. **Profile assembly** — Your top tracks (with artist attribution), top artists (with Spotify genre tags), and aggregated genres are formatted into a rich prompt.
2. **LLM query generation** — The profile is sent to GitHub Models (default model: `gpt-4o`, configurable) with a system prompt instructing it to act as a music discovery engine. It returns up to 15 Spotify search queries designed for discovery:
   - 4–5 queries for artists **similar to but different from** your current rotation
   - 3–4 genre-adjacent or cross-genre queries
   - 2–3 specific tracks or albums you’d likely enjoy
   - 2–3 left-field picks — surprising but defensible based on your pattern
3. **Search execution** — Each query is run against `GET /v1/search` (standard Spotify quota, always works).
4. **Mix assembly** — The discovery engine (`scripts/discovery.py`) combines three slots:
   - **Slot 1** (target 15): AI-recommended tracks from the search queries above
   - **Slot 2** (up to 5): Familiar anchors — shuffled tracks from the source week
   - **Slot 3** (fill to 28): Genre and artist name search fallback
5. **Deduplication** — Known tracks (from the source week) are excluded from discovery slots. If the AI engine is unavailable, the script falls back entirely to genre/artist search.

## Notes

- The script creates **one private playlist per ISO week** (e.g. `2026-W08`) when `playlist-read-private` is granted. If that playlist already exists, the script **overwrites it** — clears all existing tracks, updates the description, then repopulates with a fresh discovery mix. Without `playlist-read-private`, overwrite detection is skipped and a new playlist is created each run.
- The discovery mix targets ~28 tracks per week: up to 15 AI-recommended, up to 5 familiar anchors, and the rest from genre/artist search.
- Week `W08` is grounded on playlist data from `W07` when available. On first run (or if `W07` is missing), it falls back to your current `short_term` listening data.
- Playlist descriptions are automatically normalized and truncated to Spotify’s 300-character limit.
- If your account has too little listening history (fewer than 5 top tracks), the script exits early.
- Edit `prompts/playlist_user_prompt.md` to customize playlist descriptions, or `prompts/recommendations_prompt.md` to customize the AI discovery strategy.
- Zero pip dependencies — everything uses Python 3.12 stdlib only (plus GitHub Models for AI).
