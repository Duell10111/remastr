"""ASGI app: REST API (/api), MCP (/mcp) and the built web UI (/)."""

import contextlib
import hmac
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from remastr import __version__
from remastr.api import router
from remastr.config import Settings
from remastr.mcp_server import build_mcp
from remastr.service import Remastr

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class TokenAuth:
    """Bearer token check for /api and /mcp. The token may also be passed as ?token= (needed for <video src>)."""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and self.token
            and scope["path"].startswith(("/api", "/mcp"))
            and scope["path"] != "/api/health"
        ):
            headers = dict(scope["headers"])
            auth = headers.get(b"authorization", b"")
            supplied = auth[7:] if auth.lower().startswith(b"bearer ") else b""
            if not supplied:
                for pair in scope.get("query_string", b"").split(b"&"):
                    if pair.startswith(b"token="):
                        supplied = pair[6:]
            if not hmac.compare_digest(supplied, self.token):
                await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None, svc: Remastr | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.is_loopback and not settings.api_token:
        raise RuntimeError("REMASTR_API_TOKEN must be set when listening on a non-loopback address")
    svc = svc or Remastr(settings)
    mcp = build_mcp(svc)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        host=settings.host,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=[f"http://{h}" for h in settings.allowed_hosts],
        ),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        svc.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            svc.stop()

    app = FastAPI(title="Remastr", version=__version__, lifespan=lifespan)
    app.state.remastr = svc
    app.include_router(router)
    # Without MCP-level auth the SDK app is a single route; adding it directly avoids the /mcp -> /mcp/ redirect
    app.router.routes.extend(mcp_app.routes)
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
    app.add_middleware(TokenAuth, token=settings.api_token)
    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
