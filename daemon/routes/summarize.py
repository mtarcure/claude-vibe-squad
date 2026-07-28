"""POST /summarize endpoint proxies to Gemini 3.5 Flash."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from daemon.flash_summarizer import FlashSummarizer

router = APIRouter()


class SummarizeRequest(BaseModel):
    text: str
    instructions: str | None = None


@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    """Summarize text using Gemini 3.5 Flash."""
    try:
        summarizer = FlashSummarizer()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="summarization unavailable: GEMINI_API_KEY not set",
        ) from exc
    summary = await summarizer.summarize(req.text, req.instructions)
    return {"summary": summary}
