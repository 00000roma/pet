# services/api/routes.py
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from core.happ_routing import ROUTING_PRESETS, build_happ_deep_link
from core.subscription import get_user_links, SubscriptionError
from core.xray_config_builder import ConfigBuildError, build_client_config_json
from db.database import get_session
from db.models import User

router = APIRouter()


# ---------- Утилиты ----------

def _get_user_by_token(token: str) -> User:
    """Находит пользователя по токену или бросает 404."""
    session = get_session()
    try:
        user = session.query(User).filter_by(token=token).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Invalid token")
        return user
    finally:
        session.close()


def _get_base_url(request: Request) -> str:
    """Возвращает публичный URL — из .env или из запроса."""
    public_url = os.getenv("PUBLIC_URL", "").strip()
    if public_url:
        return public_url.rstrip("/")
    return str(request.base_url).rstrip("/")


# ---------- Основные эндпоинты ----------

@router.get("/health")
def health() -> dict:
    """Проверка, что сервер живой."""
    return {"status": "ok"}


@router.get("/sub/{token}/xray.json")
def sub_xray_json(token: str) -> Response:
    """Полный JSON-конфиг Xray для клиента (Happ, Nekoray, v2rayN)."""
    user = _get_user_by_token(token)
    try:
        config_json = build_client_config_json(user.email, primary_only=False)
    except ConfigBuildError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=config_json,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="xray-{user.email}.json"',
            "Profile-Title": "Reactive",
            "Profile-Update-Interval": "24",
        },
    )


@router.get("/sub/{token}/happ-routing", response_class=HTMLResponse)
def sub_happ_routing_page(token: str, request: Request) -> Response:
    """HTML-страница с кнопкой «Открыть в Happ» для routing."""
    user = _get_user_by_token(token)
    base = _get_base_url(request)
    deep_link = build_happ_deep_link(preset="ru", custom_name=f"Reactive | {user.email}")

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reactive Routing</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                max-width: 500px; margin: 40px auto; padding: 20px;
                background: #f5f5f7; color: #1d1d1f; text-align: center; }}
        h1 {{ font-size: 24px; }}
        p {{ color: #555; line-height: 1.5; }}
        .btn {{ display: block; background: #34c759; color: white;
                padding: 18px 24px; border-radius: 14px; text-decoration: none;
                font-size: 18px; font-weight: 600; margin: 24px 0; }}
        .btn:hover {{ background: #248a3d; }}
        .fallback {{ background: white; padding: 14px; border-radius: 8px;
                     font-family: monospace; font-size: 12px;
                     word-break: break-all; text-align: left; }}
    </style>
</head>
<body>
    <h1>Правила маршрутизации</h1>
    <p>Нажмите кнопку, чтобы применить правила в Happ.</p>
    <a class="btn" href="{deep_link}">Открыть в Happ</a>
    <p>Если не сработало — скопируйте ссылку:</p>
    <div class="fallback">{deep_link}</div>
    <script>
        setTimeout(function() {{
            window.location.href = "{deep_link}";
        }}, 500);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/sub/{token}/happ-routing/raw", response_class=PlainTextResponse)
def sub_happ_routing_raw(token: str) -> Response:
    """Сырой deep link для Happ routing."""
    user = _get_user_by_token(token)
    deep_link = build_happ_deep_link(preset="ru", custom_name=f"Reactive | {user.email}")
    return Response(content=deep_link, media_type="text/plain; charset=utf-8")


@router.get("/go/{token}", response_class=HTMLResponse)
def go_page(token: str, request: Request) -> Response:
    """Главная ссылка для пользователя — добавляет подписку в Happ."""
    user = _get_user_by_token(token)
    base = _get_base_url(request)

    sub_url = f"{base}/sub/{token}/xray.json"
    happ_link = f"happ://add/{sub_url}"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reactive VPN</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                max-width: 500px; margin: 0 auto; padding: 40px 20px;
                background: #f5f5f7; color: #1d1d1f; text-align: center; }}
        h1 {{ font-size: 28px; margin-bottom: 8px; }}
        p {{ color: #666; font-size: 16px; line-height: 1.5; }}
        .btn {{ display: block; background: #007aff; color: white;
                padding: 20px 24px; border-radius: 14px; text-decoration: none;
                font-size: 19px; font-weight: 600; margin: 24px 0; }}
        .btn:hover {{ background: #0056b3; }}
        .btn-secondary {{ background: #34c759; }}
        .btn-secondary:hover {{ background: #248a3d; }}
        .note {{ font-size: 14px; color: #999; margin-top: 30px; }}
    </style>
</head>
<body>
    <h1>Reactive VPN</h1>
    <p>Подписка для <b>{user.email}</b></p>

    <a class="btn" href="{happ_link}">Добавить подписку в Happ</a>

    <a class="btn btn-secondary"
       href="{base}/sub/{token}/happ-routing">
        Применить правила маршрутизации
    </a>

    <p class="note">Если ссылка не открылась — скопируйте её в Happ вручную:</p>
    <div style="background:white;padding:14px;border-radius:8px;
                font-family:monospace;font-size:12px;word-break:break-all;">
        {sub_url}
    </div>

    <script>
        setTimeout(function() {{
            window.location.href = "{happ_link}";
        }}, 500);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)