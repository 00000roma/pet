# core/subscription.py
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from urllib.parse import urlencode

from db.database import get_session
from db.models import Server, User, UserServer


class SubscriptionError(Exception):
    pass


@dataclass
class UserLink:
    server_name: str
    server_host: str
    link: str


def _build_vless_link(
    *,
    uuid: str,
    host: str,
    port: int,
    public_key: str,
    sni: str,
    short_id: str,
    flow: str,
    label: str,
    fingerprint: str = "chrome",
) -> str:
    """
    Собирает клиентскую ссылку vless:// для Reality + XHTTP.
    Пример:
    vless://uuid@host:port?type=xhttp&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F&path=%2Fxhttp&mode=auto#label
    """
    params = {
        "type": "xhttp",           # было "tcp"
        "security": "reality",
        "pbk": public_key,
        "fp": fingerprint,
        "sni": sni,
        "sid": short_id,
        "spx": "/",
        "path": "/xhttp",          # ← новый параметр для XHTTP
        "mode": "auto",            # ← и этот
        # flow НЕ указываем — он несовместим с XHTTP
    }
    query = urlencode(params)
    return f"vless://{uuid}@{host}:{port}?{query}#{label}"


def get_user_links(email: str) -> list[UserLink]:
    """Возвращает все ссылки для пользователя по его email."""
    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if not user:
            raise SubscriptionError(f"Пользователь с email '{email}' не найден.")

        rows = (
            session.query(UserServer, Server)
            .join(Server, UserServer.server_id == Server.id)
            .filter(UserServer.user_id == user.id)
            .order_by(Server.id)
            .all()
        )
        if not rows:
            raise SubscriptionError(f"У пользователя '{email}' нет серверов.")

        links: list[UserLink] = []
        for link_row, server in rows:
            server_names = json.loads(server.reality_server_names or "[]")
            short_ids = json.loads(server.reality_short_ids or "[]")
            if not server_names or not short_ids:
                continue  # неполные данные — пропускаем

            link = _build_vless_link(
                uuid=user.uuid,
                host=server.host,
                port=server.xray_port,
                public_key=server.reality_public_key,
                sni=server_names[0],
                short_id=short_ids[0],
                flow=link_row.flow or "xtls-rprx-vision",
                label=f"{server.name} | {email}",
            )
            links.append(
                UserLink(
                    server_name=server.name,
                    server_host=server.host,
                    link=link,
                )
            )
        return links
    finally:
        session.close()


def get_subscription_base64(email: str) -> str:
    """
    Возвращает подписку в формате Base64 (как её ожидают клиенты типа v2rayNG, Streisand).
    Внутри — список vless:// ссылок, разделённых переводом строки.
    """
    links = get_user_links(email)
    raw = "\n".join(l.link for l in links)
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return encoded