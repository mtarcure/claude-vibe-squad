"""Bearer token auth for daemon endpoints.

All endpoints except /health require Authorization: Bearer <VIBESQUAD_DAEMON_TOKEN>.
Token is read from env at daemon startup. Reject any request without a matching token.
"""
import os
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Paths that skip auth (must remain accessible for launchd health checks)
PUBLIC_PATHS = {"/health"}


class BearerTokenAuth(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.expected_token = os.environ.get("VIBESQUAD_DAEMON_TOKEN")
        if not self.expected_token:
            # Fail loud at startup — no silent auth bypass
            raise RuntimeError(
                "VIBESQUAD_DAEMON_TOKEN not set. Source ~/.config/shell/secrets.zsh "
                "before starting the daemon."
            )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "missing bearer token"},
            )

        token = header[7:].strip()
        if token != self.expected_token:
            return JSONResponse(
                status_code=403,
                content={"detail": "invalid bearer token"},
            )

        return await call_next(request)
