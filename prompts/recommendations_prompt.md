Analyse my recent listening and suggest Spotify search queries for music discovery.

Source week: {source_week}
Target week: {target_week}

My top artists:
{top_artists}

My top tracks:
{top_tracks}

Genres in rotation: {genres}

Suggest {max_queries} Spotify search queries. Each query should use Spotify search syntax (supports: artist:"name", genre:"name", track:"name", album:"name", year:YYYY, year:YYYY-YYYY).

Mix of:
- 4-5 queries for artists SIMILAR to but DIFFERENT from my current rotation
- 3-4 genre-adjacent or cross-genre queries
- 2-3 queries for specific tracks or albums I'd likely enjoy
- 2-3 left-field picks — surprising but defensible based on my listening pattern

DO NOT suggest tracks or artists already in my listening data — the goal is DISCOVERY.
Prefer queries that surface recent releases (last 2 years).
Return strict JSON with a single key: queries
