from fastapi import APIRouter, HTTPException
from daemon.mcp_manager import MANAGER

router = APIRouter()

@router.get("/catalog/search")
async def catalog_search(q: str, limit: int = 20):
    try:
        result = await MANAGER.call_tool("chrono-vault", "catalog_search", {"query": q, "limit": limit})
        return result
    except Exception as e:
        # Was HTTP 200 with {"results": [], "error": ...} -- a caller checking
        # resp.ok could not tell "no matches" from "backend unreachable".
        raise HTTPException(status_code=502, detail=f"catalog backend unavailable: {e}") from e
