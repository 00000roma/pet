from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from services.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Reactive",
        version="0.1.0",
        # Отключаем все публичные страницы документации
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Защита от Host-header атак (DNS rebinding)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "update.rktv.ru",
            "172.16.200.204",
            "localhost",
            "127.0.0.1",
        ],
    )

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index():
        return {"status": "Reactive subscription service"}

    return app


app = create_app()