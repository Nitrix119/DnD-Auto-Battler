from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import Receive, Scope, Send

from src.combat.spell_registry import SpellRegistry
from web.routers import combat, health

_WEB_DIR = Path(__file__).parent


class _NoCacheStaticFiles(StaticFiles):
    """StaticFiles that adds Cache-Control: no-cache to every response.

    Without an explicit Cache-Control header Starlette only sends ETag /
    Last-Modified, which lets browsers apply heuristic freshness and silently
    serve stale assets for minutes.  no-cache forces a conditional request on
    every load while the ETag/304 path keeps bandwidth cost negligible.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def patched_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-cache, must-revalidate"))
                message = {**message, "headers": headers}
            await send(message)

        await super().__call__(scope, receive, patched_send)


def create_app() -> FastAPI:
    application = FastAPI(title="D&D Auto Battler")

    # Global spell registry — scanned once at startup, shared across all sessions
    spell_registry = SpellRegistry()
    spell_registry.scan_directory(str(_WEB_DIR.parent / "examples" / "spells"))
    application.state.spell_registry = spell_registry

    application.mount(
        "/static",
        _NoCacheStaticFiles(directory=_WEB_DIR / "static"),
        name="static",
    )

    templates = Jinja2Templates(directory=_WEB_DIR / "templates")

    application.include_router(health.router)
    application.include_router(combat.router)

    @application.get("/", response_class=HTMLResponse)
    async def root(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("index.html", {"request": request})

    @application.get("/battle", response_class=HTMLResponse)
    async def battle(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("battle.html", {"request": request})

    return application


app = create_app()
