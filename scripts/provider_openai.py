"""OpenAI API provider implementation."""

from __future__ import annotations

from typing import Any

from provider import AIProvider
from http_client import http_json


class OpenAIProvider(AIProvider):
    """OpenAI API provider for text and image generation."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key (sk-...).
            base_url: OpenAI API base URL (default: production).
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate text using OpenAI's chat completions API.

        Returns a dict compatible with OpenAI response format:
        {"choices": [{"message": {"content": "..."}}]}
        """
        response = http_json(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            body={
                "model": model,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        return response

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str = "1024",
        quality: str = "standard",
    ) -> dict[str, Any]:
        """Generate an image using OpenAI's images API.

        Returns a dict compatible with OpenAI response format:
        {"data": [{"b64_json": "..."}]}
        """
        # Convert size format: "1024" -> "1024x1024"
        if "x" not in size:
            size_str = f"{size}x{size}"
        else:
            size_str = size

        response = http_json(
            "POST",
            f"{self.base_url}/images/generations",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            body={
                "model": model,
                "prompt": prompt,
                "size": size_str,
                "quality": quality,
                "response_format": "b64_json",
            },
        )
        return response
