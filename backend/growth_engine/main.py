"""FastAPI application: the panel API, the bot webhooks and the public pages."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    admin, agency, audits, auth, billing, brand, calendar, channels, competitors, feedback, measure, posts, recipes,
    workspaces,
)
from . import logs, migrate
from .bots import webhook
from .config import get_settings
from .errors import AppError
from .public import pages


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().auto_migrate:
        migrate.upgrade_to_head()
    yield


def create_app() -> FastAPI:
    get_settings().check_production()
    app = FastAPI(title="Growth Engine", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
    s = get_settings()
    # In development any localhost port may call the API (the panel's dev server, a second checkout).
    local = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$" if s.is_development else None
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_origin_regex=local,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    # Added last, so it is outermost and also logs what CORS refuses.
    app.middleware("http")(logs.log_requests)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        logging.getLogger("growth_engine.http").info("%s %s: %s (%s)", request.method, request.url.path,
                                                      exc.code, exc.status)
        return JSONResponse(status_code=exc.status,
                            content={"detail": {"code": exc.code, "message": exc.message, **exc.extra}})

    for module in (auth, workspaces, brand, recipes, channels, posts, calendar, feedback, competitors, measure,
                   audits, agency, billing, admin):
        app.include_router(module.router, prefix="/api")
    app.include_router(webhook.router)
    app.include_router(pages.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    return app


logs.setup()
app = create_app()
