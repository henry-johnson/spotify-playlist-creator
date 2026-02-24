from __future__ import annotations

import os
import sys
import base64
from pathlib import Path
from datetime import datetime, timedelta

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# Compute dynamic week labels relative to today
def _iso_week_label(offset_weeks: int = 0) -> str:
    d = datetime.now() + timedelta(weeks=offset_weeks)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"

SOURCE_WEEK  = _iso_week_label(0)   # current week
TARGET_WEEK  = _iso_week_label(1)   # next week

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from model_provider_openai import OpenAIProvider
from config import (
    OPENAI_TEXT_MODEL_SMALL,
    OPENAI_TEXT_MODEL_LARGE,
    OPENAI_TEMPERATURE_SMALL,
    OPENAI_TEMPERATURE_LARGE,
)
from metadata import generate_playlist_description, assemble_final_description
from recommendations import ai_recommend_search_queries
from artwork import generate_playlist_artwork_base64

# ---------------------------------------------------------------------------
# Shared demo data — shaped to match what spotify_get_top_artists /
# spotify_get_top_tracks actually return.
# ---------------------------------------------------------------------------
DEMO_TOP_ARTISTS = [
    {
        "id": "4LEiUm1SRbFMgfqnQTwUbQ",
        "name": "Bon Iver",
        "genres": ["indie folk", "folk-pop", "chamber pop", "alternative"],
        "popularity": 78,
        "followers": {"total": 6_800_000},
    },
    {
        "id": "2cCUtGK9sDU2EoElnk0GNB",
        "name": "The National",
        "genres": ["indie rock", "chamber pop", "alternative rock"],
        "popularity": 72,
        "followers": {"total": 3_200_000},
    },
    {
        "id": "4Z8W4fKeB5YxbusRsdQVPb",
        "name": "Radiohead",
        "genres": ["alternative rock", "art rock", "experimental rock"],
        "popularity": 83,
        "followers": {"total": 9_100_000},
    },
    {
        "id": "3RGLhK1IP9jnYFH4BRFJBS",
        "name": "Fleet Foxes",
        "genres": ["indie folk", "folk rock", "chamber pop"],
        "popularity": 68,
        "followers": {"total": 2_900_000},
    },
    {
        "id": "3kjuyTCjPG1Tp2EnPrNyMW",
        "name": "Arcade Fire",
        "genres": ["indie rock", "art rock", "alternative"],
        "popularity": 74,
        "followers": {"total": 4_500_000},
    },
]

DEMO_TOP_TRACKS = [
    {
        "id": "4aebBr4JAihzJQR0CiIZJv",
        "uri": "spotify:track:4aebBr4JAihzJQR0CiIZJv",
        "name": "Holocene",
        "artists": [{"id": "4LEiUm1SRbFMgfqnQTwUbQ", "name": "Bon Iver"}],
        "album": {"name": "Bon Iver, Bon Iver", "release_date": "2011-06-17"},
        "popularity": 74,
    },
    {
        "id": "0qVMdFSkn7gnNRaRicD8nz",
        "uri": "spotify:track:0qVMdFSkn7gnNRaRicD8nz",
        "name": "Skinny Love",
        "artists": [{"id": "4LEiUm1SRbFMgfqnQTwUbQ", "name": "Bon Iver"}],
        "album": {"name": "For Emma, Forever Ago", "release_date": "2008-02-19"},
        "popularity": 72,
    },
    {
        "id": "3iFkYqU3UGsRfmGEFzHZet",
        "uri": "spotify:track:3iFkYqU3UGsRfmGEFzHZet",
        "name": "Fake Plastic Trees",
        "artists": [{"id": "4Z8W4fKeB5YxbusRsdQVPb", "name": "Radiohead"}],
        "album": {"name": "The Bends", "release_date": "1995-03-13"},
        "popularity": 77,
    },
    {
        "id": "6wCH6TUMgGlFgNHKIHNHwL",
        "uri": "spotify:track:6wCH6TUMgGlFgNHKIHNHwL",
        "name": "About Today",
        "artists": [{"id": "2cCUtGK9sDU2EoElnk0GNB", "name": "The National"}],
        "album": {"name": "Sad Songs for Dirty Lovers", "release_date": "2003-10-14"},
        "popularity": 65,
    },
    {
        "id": "4MzXwWMhyBbmu6hOcI3KIT",
        "uri": "spotify:track:4MzXwWMhyBbmu6hOcI3KIT",
        "name": "Mykonos",
        "artists": [{"id": "3RGLhK1IP9jnYFH4BRFJBS", "name": "Fleet Foxes"}],
        "album": {"name": "Sun Giant", "release_date": "2008-03-18"},
        "popularity": 63,
    },
    {
        "id": "5F4agBrTFMbNqOWhN0zQY2",
        "uri": "spotify:track:5F4agBrTFMbNqOWhN0zQY2",
        "name": "White Winter Hymnal",
        "artists": [{"id": "3RGLhK1IP9jnYFH4BRFJBS", "name": "Fleet Foxes"}],
        "album": {"name": "Fleet Foxes", "release_date": "2008-06-03"},
        "popularity": 71,
    },
    {
        "id": "2gKAbCQhkZuIpCjdyFDysg",
        "uri": "spotify:track:2gKAbCQhkZuIpCjdyFDysg",
        "name": "Wake Up",
        "artists": [{"id": "3kjuyTCjPG1Tp2EnPrNyMW", "name": "Arcade Fire"}],
        "album": {"name": "Funeral", "release_date": "2004-09-14"},
        "popularity": 75,
    },
    {
        "id": "76bHmkXU29FDoXWFXNMBN0",
        "uri": "spotify:track:76bHmkXU29FDoXWFXNMBN0",
        "name": "The Wire",
        "artists": [{"id": "2cCUtGK9sDU2EoElnk0GNB", "name": "The National"}],
        "album": {"name": "Alligator", "release_date": "2005-05-17"},
        "popularity": 61,
    },
    {
        "id": "6LgJvl0Xdtc73RJ1mmpgpM",
        "uri": "spotify:track:6LgJvl0Xdtc73RJ1mmpgpM",
        "name": "Paranoid Android",
        "artists": [{"id": "4Z8W4fKeB5YxbusRsdQVPb", "name": "Radiohead"}],
        "album": {"name": "OK Computer", "release_date": "1997-05-21"},
        "popularity": 81,
    },
    {
        "id": "1lyEMpHAgweCHzPeE8HAZE",
        "uri": "spotify:track:1lyEMpHAgweCHzPeE8HAZE",
        "name": "Re: Stacks",
        "artists": [{"id": "4LEiUm1SRbFMgfqnQTwUbQ", "name": "Bon Iver"}],
        "album": {"name": "For Emma, Forever Ago", "release_date": "2008-02-19"},
        "popularity": 68,
    },
]


def _get_provider() -> OpenAIProvider | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not set")
        return None
    return OpenAIProvider(api_key=api_key)


def test_text_generation_small():
    """Test description generation via the real metadata pipeline."""
    provider = _get_provider()
    if not provider:
        return False

    try:
        description = generate_playlist_description(
            provider=provider,
            top_tracks=DEMO_TOP_TRACKS,
            temperature=OPENAI_TEMPERATURE_SMALL,
            source_week=SOURCE_WEEK,
            target_week=TARGET_WEEK,
            listener_first_name="Henry",
        )
        final = assemble_final_description(description)
        print(f"✅ Description ({OPENAI_TEXT_MODEL_SMALL}): {final[:120]}...")
        output_path = Path(__file__).parent / f"generated_description_{TIMESTAMP}.txt"
        output_path.write_text(
            f"Model: {OPENAI_TEXT_MODEL_SMALL}\n"
            f"Source: {SOURCE_WEEK}  Target: {TARGET_WEEK}\n"
            f"Length: {len(final)} chars\n\n"
            f"{final}\n"
        )
        print(f"   Length: {len(final)} chars")
        print(f"   Saved to: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Description generation failed: {e}")
        return False


def test_text_generation_large():
    """Test recommendations via the real discovery pipeline."""
    provider = _get_provider()
    if not provider:
        return False

    try:
        queries = ai_recommend_search_queries(
            provider=provider,
            top_tracks=DEMO_TOP_TRACKS,
            top_artists=DEMO_TOP_ARTISTS,
            source_week=SOURCE_WEEK,
            target_week=TARGET_WEEK,
            temperature=OPENAI_TEMPERATURE_LARGE,
            max_queries=15,
        )
        print(f"✅ Recommendations ({OPENAI_TEXT_MODEL_LARGE}): {len(queries)} queries")
        for q in queries[:3]:
            print(f"   • {q}")
        output_path = Path(__file__).parent / f"generated_recommendations_{TIMESTAMP}.txt"
        output_path.write_text(
            f"Model: {OPENAI_TEXT_MODEL_LARGE}\n"
            f"Source: {SOURCE_WEEK}  Target: {TARGET_WEEK}\n\n"
            + "\n".join(queries) + "\n"
        )
        print(f"   Saved to: {output_path}")
        return bool(queries)
    except Exception as e:
        print(f"❌ Recommendations generation failed: {e}")
        return False


def test_image_generation():
    """Test artwork generation for the next week."""
    provider = _get_provider()
    if not provider:
        return False
    
    try:
        artwork_b64 = generate_playlist_artwork_base64(
            provider=provider,
            top_tracks=DEMO_TOP_TRACKS,
            top_artists=DEMO_TOP_ARTISTS,
            source_week=SOURCE_WEEK,
            target_week=TARGET_WEEK,
            playlist_name=TARGET_WEEK,
        )
        
        if not artwork_b64:
            print("❌ Artwork generation returned None")
            return False
        
        image_bytes = base64.b64decode(artwork_b64)
        size_kb = len(image_bytes) / 1024
        print(f"✅ Image generated with demo data: {size_kb:.1f} KB")
        
        # Save to disk with shared timestamp
        output_path = Path(__file__).parent / f"generated_artwork_{TIMESTAMP}.jpg"
        output_path.write_bytes(image_bytes)
        print(f"   Saved to: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Artwork generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_image_generation_next_3_weeks():
    """Generate artwork for the 3 weeks after TARGET_WEEK."""
    provider = _get_provider()
    if not provider:
        return False

    weeks = [
        (_iso_week_label(1), _iso_week_label(2)),
        (_iso_week_label(2), _iso_week_label(3)),
        (_iso_week_label(3), _iso_week_label(4)),
    ]
    all_ok = True

    for source_week, target_week in weeks:
        try:
            artwork_b64 = generate_playlist_artwork_base64(
                provider=provider,
                top_tracks=DEMO_TOP_TRACKS,
                top_artists=DEMO_TOP_ARTISTS,
                source_week=source_week,
                target_week=target_week,
                playlist_name=target_week,
            )
            if not artwork_b64:
                print(f"❌ Artwork generation returned None for {target_week}")
                all_ok = False
                continue
            image_bytes = base64.b64decode(artwork_b64)
            size_kb = len(image_bytes) / 1024
            print(f"✅ Image generated for {target_week}: {size_kb:.1f} KB")
            output_path = Path(__file__).parent / f"generated_artwork_{target_week}_{TIMESTAMP}.jpg"
            output_path.write_bytes(image_bytes)
            print(f"   Saved to: {output_path}")
        except Exception as e:
            print(f"❌ Artwork generation failed for {target_week}: {e}")
            import traceback
            traceback.print_exc()
            all_ok = False

    return all_ok


if __name__ == "__main__":
    single = "--single" in sys.argv
    print("Testing OpenAI Provider...\n")

    results = [
        ("Description", test_text_generation_small()),
        ("Recommendations", test_text_generation_large()),
        (f"Image ({TARGET_WEEK})", test_image_generation()),
    ]
    if not single:
        results.append(
            (f"Image ({_iso_week_label(2)}–{_iso_week_label(4)})", test_image_generation_next_3_weeks())
        )
    print("\n" + "="*50)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    sys.exit(0 if all_passed else 1)
