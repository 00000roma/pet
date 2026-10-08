# services/api/routes.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse

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
    """Метаданные о подписке — сколько серверов, какие."""
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
    }