"""Gemini client restricted to the two approved Flash-Lite models."""

from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import Final

from google import genai
from google.genai import errors, types

from src.config import get_settings

ALLOWED_GEMINI_MODELS: Final[tuple[str, str]] = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
)


@dataclass(frozen=True)
class GeminiResult:
    text: str
    model: str
    failed_over: bool = False


class GeminiRoundRobin:
    """Alternate models per request and retry only quota failures once."""

    def __init__(self, api_key: str, client=None) -> None:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=60_000),
        )
        self._next_index = 0
        self._selection_lock = Lock()

    def _select_models(self) -> tuple[str, str]:
        with self._selection_lock:
            primary_index = self._next_index
            self._next_index = (self._next_index + 1) % len(ALLOWED_GEMINI_MODELS)
        return (
            ALLOWED_GEMINI_MODELS[primary_index],
            ALLOWED_GEMINI_MODELS[1 - primary_index],
        )

    async def _generate_with(self, model: str, prompt: str) -> str:
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=2048),
        )
        text = response.text
        if not text:
            raise RuntimeError(f"Gemini model {model} returned no text")
        return text

    async def generate(self, prompt: str) -> GeminiResult:
        primary, alternate = self._select_models()
        try:
            text = await self._generate_with(primary, prompt)
            return GeminiResult(text=text, model=primary)
        except errors.APIError as exc:
            if exc.code != 429:
                raise

        text = await self._generate_with(alternate, prompt)
        return GeminiResult(text=text, model=alternate, failed_over=True)

    async def aclose(self) -> None:
        """Release sync and async transports owned by the Google SDK."""
        await self._client.aio.aclose()
        self._client.close()


@lru_cache
def get_llm() -> GeminiRoundRobin:
    api_key = get_settings().gemini_api_key.get_secret_value()
    return GeminiRoundRobin(api_key=api_key)
