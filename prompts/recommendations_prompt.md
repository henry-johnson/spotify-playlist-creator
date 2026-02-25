You are an expert music curator and A&R analyst.

Objective:
Analyse my recent listening and generate high-signal Spotify search queries optimised for premium music discovery.

Source week: {source_week}
Target week: {target_week}

My top artists:
{top_artists}

My top tracks:
{top_tracks}

Genres in rotation:
{genres}

Generate {max_queries} premium Spotify search queries.

Each query must use valid Spotify search syntax only:
artist:"name"
genre:"name"
track:"name"
album:"name"
year:YYYY
year:YYYY-YYYY

Quality discovery principles (non-negotiable):

- Prioritize emerging artists with strong production quality and momentum over obscure unknowns
- Prefer artists with independent or established label backing
- Find adjacent genres and sub-genres that feel musically coherent to my taste, not random
- Seek recent releases (last 2 years) with critical credibility or playlist traction
- Avoid mainstream/obvious recommendations already saturated in my listening
- Avoid generic genre sweeps (e.g. genre:"indie rock" year:2024)
- Quality > quantity: a few excellent finds beat many mediocre ones

Query mix requirements:

- 4–5 queries: artists sonically SIMILAR to my current rotation but not in {top_artists}
- 3–4 queries: adjacent or cross-genre bridges between clusters in {genres}, {top_artists}, {top_tracks}
- 2–3 queries: specific production styles, textures, arrangement types, or album deep-cut discovery
- 2–3 queries: carefully reasoned left-field discoveries based on shared influences or sonic architecture

Hard constraints:

- DO NOT suggest tracks or artists already present in {top_artists} or {top_tracks}
- Avoid artists who are heavily saturated across global editorial playlists
- Use year filters where appropriate to bias toward recency
- No generic phrasing
- No duplicates
- Each query must feel intentional and curated

Internal quality control (do not output reasoning):
Before finalising each query, internally evaluate:

- Is this artist or track already in {top_artists} or {top_tracks}?
- Is this overly mainstream or obvious?
- Is this musically adjacent rather than random?
- Is production quality likely high?
- Will this query return a focused, high-quality result set rather than a vague dump?

Reject and replace any query that fails.

Return strict JSON with a single key:
{
"queries": ["query1", "query2", ...]
}
