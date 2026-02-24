"""AI-powered playlist artwork generation."""

from __future__ import annotations

import base64
import binascii
import colorsys
import io
import os
import sys
import urllib.request
from typing import Any

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from model_provider import AIProvider
from config import (
    DEFAULT_ARTWORK_PROMPT_FILE,
    OPENAI_IMAGE_MODEL,
    OPENAI_IMAGE_QUALITY,
    OPENAI_IMAGE_SIZE,
    SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES,
    read_file_if_exists,
)


# Helvetica Neue TTC face indices on macOS (verified)
_HELVETICA_NEUE_TTC = "/System/Library/Fonts/HelveticaNeue.ttc"
_HELVETICA_NEUE_INDICES = {"regular": 0, "bold": 1, "light": 7, "medium": 10}
_FALLBACK_FONTS = [
    "/Library/Fonts/Helvetica Neue.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _default_artwork_prompt_template() -> str:
    """Fallback prompt for playlist artwork generation."""
    return (
        "Create square album-cover-style artwork for a weekly Spotify playlist.\n"
        "Target week: {target_week}\n"
        "Source week: {source_week}\n"
        "Style notes: modern, moody, abstract, soft gradient. "
        "No text, no logos, no faces.\n"
        "Output should be suitable as a playlist cover image."
    )


def _build_artwork_prompt(
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
    playlist_name: str = "Weekly Playlist",
) -> str:
    """Build the user prompt for image generation."""
    prompt_file = os.getenv("PLAYLIST_ARTWORK_PROMPT_FILE", DEFAULT_ARTWORK_PROMPT_FILE)
    template = read_file_if_exists(prompt_file) or _default_artwork_prompt_template()

    # If template has placeholders, format them; otherwise use as-is
    if "{" in template and "}" in template:
        artist_names = ", ".join(
            dict.fromkeys(
                [a.get("name", "") for a in top_artists if a.get("name")]
                + [
                    artist.get("name", "")
                    for track in top_tracks
                    for artist in track.get("artists", [])
                    if artist.get("name")
                ]
            )
        )
        track_names = ", ".join(
            track.get("name", "") for track in top_tracks[:12] if track.get("name")
        )

        return template.format(
            playlist_name=playlist_name,
            source_week=source_week,
            target_week=target_week,
            top_artists=artist_names or "Unknown",
            top_tracks=track_names or "Unknown",
        )
    
    return template


def _load_font(size: int, weight: str = "regular") -> Any:
    """Load Helvetica Neue at the given size, falling back to system fonts."""
    from PIL import ImageFont  # type: ignore

    # Try Helvetica Neue TTC (macOS)
    if os.path.exists(_HELVETICA_NEUE_TTC):
        index = _HELVETICA_NEUE_INDICES.get(weight, 0)
        try:
            return ImageFont.truetype(_HELVETICA_NEUE_TTC, size=size, index=index)
        except Exception:
            try:
                return ImageFont.truetype(_HELVETICA_NEUE_TTC, size=size, index=0)
            except Exception:
                pass

    # Fallback fonts
    for path in _FALLBACK_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue

    return ImageFont.load_default()


def _fit_font_to_width(
    draw: Any,
    text: str,
    target_width: int,
    weight: str = "medium",
    *,
    min_size: int = 20,
    max_size: int = 600,
) -> Any:
    """Binary-search for font size that makes text span target_width pixels."""
    lo, hi = min_size, max_size
    best = _load_font(min_size, weight)

    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid, weight)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        if text_width <= target_width:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1

    return best


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG relative luminance of an sRGB colour."""
    def _lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two RGB colours."""
    l1 = _relative_luminance(*c1)
    l2 = _relative_luminance(*c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _pick_colour_for_region(
    img: Any,
    crop_box: tuple[int, int, int, int],
    *,
    min_contrast: float = 4.5,
    label: str = "region",
) -> tuple[int, int, int]:
    """Derive a high-contrast hue-matched colour for a given image region.

    Samples the dominant colour in crop_box, then produces a light or dark
    shade of the same hue that passes WCAG contrast against the background.
    """
    region = img.crop(crop_box)
    quantized = region.quantize(colors=8, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colour_counts: dict[tuple[int, int, int], int] = {}
    for pixel in quantized.getdata():
        colour_counts[pixel] = colour_counts.get(pixel, 0) + 1  # type: ignore[index]

    bg_colour = max(colour_counts, key=lambda c: colour_counts[c])
    bg_lum = _relative_luminance(*bg_colour)

    r, g, b = (c / 255.0 for c in bg_colour)
    h_val, l_val, s_val = colorsys.rgb_to_hls(r, g, b)

    if bg_lum < 0.4:
        target_l = 0.90
        target_s = min(s_val + 0.15, 1.0)
    else:
        target_l = 0.12
        target_s = min(s_val + 0.2, 1.0)

    tr, tg, tb = colorsys.hls_to_rgb(h_val, target_l, target_s)
    candidate = (int(tr * 255), int(tg * 255), int(tb * 255))
    ratio = _contrast_ratio(candidate, bg_colour)

    print(
        f"  [{label}] colour: rgb{candidate} (bg rgb{bg_colour}, contrast {ratio:.2f}:1)",
        file=sys.stderr, flush=True,
    )

    if ratio < min_contrast:
        fallback = (255, 255, 255) if bg_lum < 0.5 else (0, 0, 0)
        print(
            f"  [{label}] contrast {ratio:.2f}:1 < {min_contrast} — "
            f"falling back to {'white' if fallback[0] == 255 else 'black'}",
            file=sys.stderr, flush=True,
        )
        return fallback

    return candidate


def _pick_name_colour(
    img: Any,
    *,
    min_contrast: float = 4.5,
) -> tuple[int, int, int]:
    """Pick a palette-derived colour for the centre-positioned playlist name."""
    w, h = img.size
    cx, cy = w // 2, h // 2
    half_w, half_h = w // 4, h // 4
    crop_box = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    return _pick_colour_for_region(img, crop_box, min_contrast=min_contrast, label="name")


def _render_text_overlay(
    image_bytes: bytes,
    playlist_name: str,
    *,
    name_width_pct: float = 0.75,
    footer_from_bottom_pct: float = 0.05,
) -> bytes:
    """Render playlist name + footer onto the image using Pillow.

    Guarantees zero shadow, exact positioning, and consistent Helvetica Neue font.
    """
    if not PIL_AVAILABLE:
        print("  Pillow not available — skipping text overlay.", file=sys.stderr, flush=True)
        return image_bytes

    try:
        from PIL import ImageDraw  # type: ignore

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = img.size
        draw = ImageDraw.Draw(img)

        # --- Playlist name: 75% of image width, centered both axes ---
        target_name_width = int(width * name_width_pct)
        name_font = _fit_font_to_width(draw, playlist_name, target_name_width, weight="medium")
        name_colour = _pick_name_colour(img)
        # anchor="mm" centers the text at the given (x, y) point exactly
        cx, cy = width // 2, height // 2
        draw.text((cx, cy), playlist_name, fill=name_colour, font=name_font, anchor="mm")

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=95, optimize=True)
        result = out.getvalue()
        print(
            f"  Text overlay rendered (Pillow/Helvetica Neue): "
            f"{len(image_bytes)} → {len(result)} bytes",
            file=sys.stderr,
            flush=True,
        )
        return result

    except Exception as err:
        print(f"  Text overlay failed: {err}. Returning image without text.", file=sys.stderr, flush=True)
        return image_bytes


def _extract_base64_image(response: dict[str, Any]) -> str | None:
    """Extract base64 image data from an OpenAI-compatible image response."""
    data = response.get("data")
    if not isinstance(data, list) or not data:
        return None

    first = data[0]
    if not isinstance(first, dict):
        return None

    b64_json = first.get("b64_json")
    if isinstance(b64_json, str) and b64_json.strip():
        return b64_json.strip()

    image_url = first.get("url")
    if isinstance(image_url, str) and image_url.strip():
        try:
            with urllib.request.urlopen(image_url) as resp:
                raw = resp.read()
            return base64.b64encode(raw).decode("ascii")
        except Exception as exc:
            print(f"  Artwork fetch failed: {exc}", file=sys.stderr, flush=True)
            return None

    return None


def _compress_image_if_needed(
    image_bytes: bytes,
    max_bytes: int = SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES,
    target_quality: int = 95,
) -> bytes:
    """Compress JPEG image to fit within Spotify's size limit if needed."""
    if len(image_bytes) <= max_bytes:
        return image_bytes

    if not PIL_AVAILABLE:
        print(
            f"  Image too large ({len(image_bytes)} bytes) and PIL not available. "
            f"Install Pillow to compress: pip install Pillow",
            file=sys.stderr,
            flush=True,
        )
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "LA"):
            # Convert RGBA to RGB for JPEG
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[3] if img.mode == "RGBA" else img.split()[1])
            img = rgb_img

        # Fine-grained quality reduction for precise compression targeting
        quality = target_quality
        while quality >= 60:
            compressed_io = io.BytesIO()
            img.save(compressed_io, format="JPEG", quality=quality, optimize=True)
            compressed_bytes = compressed_io.getvalue()

            if len(compressed_bytes) <= max_bytes:
                print(
                    f"  Compressed artwork: {len(image_bytes)} → "
                    f"{len(compressed_bytes)} bytes (quality: {quality})",
                    file=sys.stderr,
                    flush=True,
                )
                return compressed_bytes

            quality -= 2

        print(
            f"  Image compression failed: could not get below {max_bytes} bytes. "
            f"Using original.",
            file=sys.stderr,
            flush=True,
        )
        return image_bytes
    except Exception as err:
        print(
            f"  Image compression error: {err}. Using original.",
            file=sys.stderr,
            flush=True,
        )
        return image_bytes


def generate_playlist_artwork_base64(
    provider: AIProvider,
    top_tracks: list[dict[str, Any]],
    top_artists: list[dict[str, Any]],
    *,
    source_week: str,
    target_week: str,
    playlist_name: str = "Weekly Playlist",
) -> str | None:
    """Generate playlist artwork and return base64-encoded JPEG bytes.

    Returns None on failure or if image validation fails.
    """
    prompt = _build_artwork_prompt(
        top_tracks,
        top_artists,
        source_week=source_week,
        target_week=target_week,
        playlist_name=playlist_name,
    )

    print(f"  Artwork AI: calling {OPENAI_IMAGE_MODEL}…", flush=True)

    try:
        response = provider.generate_image(
            prompt,
            model=OPENAI_IMAGE_MODEL,
            size=OPENAI_IMAGE_SIZE,
            quality=OPENAI_IMAGE_QUALITY,
        )
    except Exception as exc:
        print(f"  Artwork AI failed: {exc}", file=sys.stderr, flush=True)
        return None

    image_b64 = _extract_base64_image(response)
    if not image_b64:
        print("  Artwork AI returned no image payload.", file=sys.stderr, flush=True)
        return None

    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        print("  Artwork payload was not valid base64.", file=sys.stderr, flush=True)
        return None

    # Render text overlay via Pillow (guarantees zero shadow, exact positioning)
    image_bytes = _render_text_overlay(image_bytes, playlist_name)

    # Compress if needed to fit Spotify's limit
    image_bytes = _compress_image_if_needed(image_bytes)

    if len(image_bytes) > SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES:
        print(
            "  Artwork still too large after compression "
            f"({len(image_bytes)} bytes > {SPOTIFY_PLAYLIST_IMAGE_MAX_BYTES}). "
            "Skipping upload.",
            file=sys.stderr,
            flush=True,
        )
        return None

    return base64.b64encode(image_bytes).decode("ascii")
