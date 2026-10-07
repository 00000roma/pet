# services/api/app.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from services.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Xray Manager Subscription API",
        version="0.1.0",
        description="HTTP-сервер, отдающий подписки для Xray-клиентов.",
    )

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse(url="/docs")

    return app


app = create_app()