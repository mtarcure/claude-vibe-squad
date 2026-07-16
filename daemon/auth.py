"""Bearer token auth for daemon HTTP and WebSocket endpoints."""
import os
import secrets

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

# Paths that skip auth (must remain accessible for launchd health checks)
PUBLIC_PATHS = {"/health"}


class BearerTokenAuth:
    """Authenticate HTTP and WebSocket scopes before routing them."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.expected_token = os.environ.get("VIBESQUAD_DAEMON_TOKEN")
        if not self.expected_token:
            # Fail loud at startup — no silent auth bypass
            raise RuntimeError(
                "VIBESQUAD_DAEMON_TOKEN not set. Source ~/.config/shell/secrets.zsh "
                "before starting the daemon."
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        if scope_type == "http" and scope.get("path") in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        header = Headers(scope=scope).get("authorization", "")
        if not header.lower().startswith("bearer "):
            await self._reject(scope, receive, send, 401, "missing bearer token")
            return

        token = header[7:].strip()
        if not secrets.compare_digest(token, self.expected_token):
            await self._reject(scope, receive, send, 403, "invalid bearer token")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": detail})
            return
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(scope, receive, send)
