# core/links.py
"""Единая точка генерации публичных ссылок подписки.

Все ссылки вида {PUBLIC_URL}/go/{token} и т.п. строятся только здесь,
чтобы CLI и HTTP-сервис не расходились.
"""
from __future__ import annotations

import os


def get_public_url() -> str:
    """Публичный URL сервиса подписок.

    Берётся из PUBLIC_URL; если не задан — http://127.0.0.1:{HTTP_PORT}.
    """
    public_url = os.getenv("PUBLIC_URL", "").strip()
    if public_url:
        return public_url.rstrip("/")
    port = os.getenv("HTTP_PORT", "8080").strip() or "8080"
    return f"http://127.0.0.1:{port}"


def get_go_url(token: str) -> str:
    """Короткая ссылка для пользователя: {PUBLIC_URL}/go/{token}."""
    return f"{get_public_url()}/go/{token}"


def get_sub_url(token: str) -> str:
    """Base64-подписка: {PUBLIC_URL}/sub/{token}."""
    return f"{get_public_url()}/sub/{token}"


def get_json_url(token: str) -> str:
    """Полный JSON-конфиг: {PUBLIC_URL}/sub/{token}/xray.json."""
    return f"{get_public_url()}/sub/{token}/xray.json"
