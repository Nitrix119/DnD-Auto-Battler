from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routers import health

_WEB_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    application = FastAPI(title="D&D Auto Battler")

    application.mount(
        "/static",
        StaticFiles(directory=_WEB_DIR / "static"),
        name="static",
    )

    templates = Jinja2Templates(directory=_WEB_DIR / "templates")

    application.include_router(health.router)

    @application.get("/", response_class=HTMLResponse)
    async def root(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("index.html", {"request": request})

    @application.get("/battle", response_class=HTMLResponse)
    async def battle(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("battle.html", {"request": request})

    return application


app = create_app()
