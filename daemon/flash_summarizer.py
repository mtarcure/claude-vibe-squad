"""Gemini 3.5 Flash synchronous summarizer for daemon."""
import os
import httpx
from typing import Optional

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"


class FlashSummarizer:
    """Wraps Gemini 3.5 Flash API for summarization."""

    def __init__(self, model: str = "gemini-3.5-flash"):
        self.model = model
        self.key = os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY not set")

    async def summarize(self, text: str, instructions: Optional[str] = None) -> str:
        """Summarize text using Flash model."""
        prompt = (instructions or "Summarize concisely with structure.") + "\n\n" + text
        url = f"{GEMINI_API}/models/{self.model}:generateContent?key={self.key}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
