"""HTTP JSON request helper with retry support."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from config import MAX_RETRIES, RETRY_BACKOFF


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    form: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Make an HTTP request and return parsed JSON."""
    request_headers = {"Accept": "application/json", **(headers or {})}

    data: bytes | None = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    elif form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode("utf-8")

    request = urllib.request.Request(
        url, data=data, headers=request_headers, method=method,
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request) as response:
                content = response.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as err:
            details = err.read().decode("utf-8", errors="replace")
            # Retry on 429 (rate limit) and 5xx (server errors)
            if err.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = RETRY_BACKOFF * (attempt + 1)
                print(
                    f"HTTP {err.code} on attempt {attempt + 1}/{retries}. "
                    f"Retrying in {wait:.1f}s…",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            print(
                f"HTTP error {err.code} for {method} {url}: {details}",
                file=sys.stderr,
            )
            raise

    # Should not be reached, but satisfies type checker
    raise RuntimeError(f"All {retries} retries exhausted for {method} {url}")
