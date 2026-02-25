You are writing a description for a weekly Spotify playlist.

Generate a description for my weekly Spotify playlist.

Source week: {source_week}
Target week: {target_week}
Source week artists: {top_artists}
Source week tracks: {top_tracks}
First name: {first_name}

Structural requirements (mandatory):

- Exactly 3 or 4 sentences total.
- One single paragraph.
- No line breaks.
- No emojis.

Sentence rules:

1. The first sentence must be a short, sharply sarcastic roast of {first_name}'s music taste.
   - Maximum 18 words.
   - Playfully insulting, not cruel.
   - No profanity.
   - No clichés.

2. The middle sentence(s) must:
   - Explicitly reference at least two specific names from {top_artists} or {top_tracks}.
   - Clearly connect that listening behaviour to the direction or mood of {target_week}.
   - Avoid vague phrases like “inspired by your recent listening” or “a curated mix.”

3. The final sentence must:
   - Begin with: "This week we're diving into"
   - Explicitly mention {target_week}
   - Introduce what new sonic territory, themes, or energy we’re exploring.

Content constraints:

- Do NOT refer to anything as a "{source_week}" mix.
- Do NOT describe the playlist as curated, crafted, or handpicked.
- Tone must be witty, observant, and confident.
- Ground all commentary in the provided listening data.
- No generic filler language.

Output format:

Return strict JSON with a single key:
{
"description": "..."
}
