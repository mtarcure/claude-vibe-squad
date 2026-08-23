"""Gemini 3.7 Flash synchronous summarizer for daemon."""
import os
import httpx
from typing import Optional

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"


class FlashSummarizer:
    """Wraps Gemini 3.7 Flash API for summarization."""

    def __init__(self, model: str = "gemini-3.7-flash"):
        self.model = model
        self.key = os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY not set")

    async def summarize(self, text: str, instructions: Optional[str] = None) -> str:
        """Summarize text using Flash model."""
        prompt = (instructions or "Summarize concisely with structure.") + "\n\n" + text
        # The key goes in a HEADER, never the query string. httpx puts the
        # request URL into HTTPStatusError's message, and the caller in
        # routes/summarize.py catches only the constructor's RuntimeError -- so
        # with `?key=` an ordinary upstream 429 or 4xx raised a live credential
        # into the exception text, and from there into whatever collects daemon
        # stderr. Header transport is what Google documents and keeps the secret
        # out of the URL that error paths echo.
        url = f"{GEMINI_API}/models/{self.model}:generateContent"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": self.key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
