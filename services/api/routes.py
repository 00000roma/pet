# services/api/routes.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse

from fastapi.responses import HTMLResponse
from core.happ_routing import build_happ_deep_link, ROUTING_PRESETS

from core.subscription import (
    get_user_links,
    get_subscription_base64,
    SubscriptionError,
)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Проверка, что сервер живой."""
    return {"status": "ok"}


@router.get("/sub/{email}", response_class=PlainTextResponse)
def sub_base64(email: str) -> Response:
    """
    Основной эндпоинт подписки.
    Возвращает Base64-encoded список vless:// ссылок.

    Клиенты (v2rayNG, Streisand, Nekoray) поймут такой ответ,
    если подписка настроена в URL-режиме.
    """
    try:
        encoded = get_subscription_base64(email)
    except SubscriptionError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=encoded,
        media_type="text/plain; charset=utf-8",
        headers={
            # Заголовок, который ожидают многие клиенты:
            "Profile-Update-Interval": "24",
            # Имя подписки (используется некоторыми клиентами):
            "Profile-Title": f"Reactive",
        },
    )


@router.get("/sub/{email}/raw", response_class=PlainTextResponse)
def sub_raw(email: str) -> Response:
    """
    Сырая подписка — просто список vless:// ссылок через \\n.
    Удобно для отладки в браузере.
    """
    try:
        links = get_user_links(email)
    except SubscriptionError as e:
        raise HTTPException(status_code=404, detail=str(e))

    raw = "\n".join(item.link for item in links)
    return Response(
        content=raw,
        media_type="text/plain; charset=utf-8",
    )


@router.get("/sub/{email}/info")
def sub_info(email: str) -> dict:
    """Метаданные о подписке — сколько серверов, какие + все URL."""
    try:
        links = get_user_links(email)
    except SubscriptionError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "email": email,
        "servers_count": len(links),
        "servers": [
            {
                "name": item.server_name,
                "host": item.server_host,
            }
            for item in links
        ],
        "urls": {
            "base64": f"/sub/{email}",
            "raw": f"/sub/{email}/raw",
            "xray_json": f"/sub/{email}/xray.json",
            "happ_routing_page": f"/sub/{email}/happ-routing",
            "happ_routing_raw": f"/sub/{email}/happ-routing/raw",
        },
    }


@router.get("/sub/{email}/happ-routing/raw", response_class=PlainTextResponse)
def sub_happ_routing_raw(
    email: str,
    preset: str = "ru",
) -> Response:
    """Сырой deep link happ://routing/add/... — для копирования."""
    if preset not in ROUTING_PRESETS:
        raise HTTPException(status_code=400, detail=f"Неизвестный preset: {preset}")
    deep_link = build_happ_deep_link(preset=preset, custom_name=f"Reactive | {email}")
    return Response(content=deep_link, media_type="text/plain; charset=utf-8")


@router.get("/sub/{email}/happ-routing", response_class=HTMLResponse)
def sub_happ_routing_page(
    email: str,
    preset: str = "ru",
) -> Response:
    """HTML-страница с кнопкой «Открыть в Happ»."""
    if preset not in ROUTING_PRESETS:
        raise HTTPException(status_code=400, detail=f"Неизвестный preset: {preset}")

    deep_link = build_happ_deep_link(preset=preset, custom_name=f"Reactive | {email}")

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reactive Routing для Happ</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            max-width: 600px; margin: 40px auto; padding: 20px;
            background: #f5f5f7; color: #1d1d1f;
        }}
        h1 {{ font-size: 24px; margin-bottom: 8px; }}
        p {{ color: #555; line-height: 1.5; }}
        .btn {{
            display: inline-block; background: #007aff; color: white;
            padding: 16px 32px; border-radius: 12px;
            text-decoration: none; font-size: 18px; font-weight: 600;
            margin: 20px 0;
        }}
        .fallback {{
            background: white; padding: 16px; border-radius: 8px;
            font-family: monospace; word-break: break-all;
            font-size: 12px; margin-top: 20px;
        }}
        .note {{ font-size: 14px; color: #888; margin-top: 30px; }}
    </style>
</head>
<body>
    <h1>Reactive Routing</h1>
    <p>Импорт правил маршрутизации в Happ для <b>{email}</b>.</p>
    <p>Пресет: <b>{preset}</b></p>

    <a class="btn" href="{deep_link}">Открыть в Happ</a>

    <p class="note">Если кнопка не сработала — скопируй ссылку ниже
    и в Happ выбери «Импорт из буфера»:</p>
    <div class="fallback">{deep_link}</div>

    <script>
        setTimeout(function() {{
            window.location.href = "{deep_link}";
        }}, 800);
    </script>
</body>
</html>"""

    return HTMLResponse(content=html)

@router.get("/sub/{email}/xray.json")
def sub_xray_json(email: str) -> Response:
    """Полный JSON-конфиг Xray с правилами маршрутизации."""
    from core.xray_config_builder import build_client_config_json, ConfigBuildError

    try:
        config_json = build_client_config_json(email, primary_only=False)
    except ConfigBuildError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=config_json,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="xray-{email}.json"',
            "Profile-Title": "Reactive",
        },
    )
