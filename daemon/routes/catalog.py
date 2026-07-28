from fastapi import APIRouter
from daemon.mcp_manager import MANAGER

router = APIRouter()

@router.get("/catalog/search")
async def catalog_search(q: str, limit: int = 20):
    try:
        result = await MANAGER.call_tool("chrono-vault", "catalog_search", {"query": q, "limit": limit})
        return result
    except Exception as e:
        # If MCP tool doesn't exist or fails, return graceful empty result
        return {"results": [], "error": str(e)}
