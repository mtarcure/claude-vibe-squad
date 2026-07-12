"""POST /summarize endpoint proxies to Gemini 3.5 Flash."""
from fastapi import APIRouter
from pydantic import BaseModel
from daemon.flash_summarizer import SUMMARIZER

router = APIRouter()


class SummarizeRequest(BaseModel):
    text: str
    instructions: str | None = None


@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    """Summarize text using Gemini 3.5 Flash."""
    summary = await SUMMARIZER.summarize(req.text, req.instructions)
    return {"summary": summary}
