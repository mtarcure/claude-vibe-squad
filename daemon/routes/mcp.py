from fastapi import APIRouter, HTTPException
from daemon.mcp_manager import MANAGER

router = APIRouter()


@router.post("/mcp/{server}/{tool}")
async def call_mcp_tool(server: str, tool: str, arguments: dict = None):
    try:
        result = await MANAGER.call_tool(server, tool, arguments or {})
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
