# core/subscription.py
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from urllib.parse import urlencode

from core.flags import get_flag_for_server
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
    label: str,
    network: str = "xhttp",           # ← xhttp | grpc
    grpc_service_name: str = "",      # ← для gRPC
    xhttp_path: str = "/xhttp",       # ← для XHTTP
    xhttp_mode: str = "auto",         # ← для XHTTP
    xhttp_host: str = "",             # ← для XHTTP (HTTP Host header)
    fingerprint: str = "chrome",
) -> str:
    """
    Собирает клиентскую ссылку vless:// для Reality + XHTTP/gRPC.

    Пример XHTTP:
      vless://uuid@host:port?type=xhttp&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F&path=%2Fxhttp&mode=auto&host=example.com#label

    Пример gRPC:
      vless://uuid@host:port?type=grpc&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F&serviceName=reactive#label
    """
    params = {
        "type": network,
        "security": "reality",
        "pbk": public_key,
        "fp": fingerprint,
        "sni": sni,
        "sid": short_id,
        "spx": "/",
    }

    if network == "xhttp":
        params["path"] = xhttp_path
        params["mode"] = xhttp_mode
        if xhttp_host:
            params["host"] = xhttp_host
    elif network == "grpc":
        params["serviceName"] = grpc_service_name

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
                continue

            # ← ФЛАГ для имени сервера
            flag = get_flag_for_server(server.name)

            link = _build_vless_link(
                uuid=link_row.uuid,
                host=server.host,
                port=server.xray_port,
                public_key=server.reality_public_key,
                sni=server_names[0],
                short_id=short_ids[0],
                label=f"{flag} {server.name} | {email}",
                network=server.network or "xhttp",
                grpc_service_name=server.grpc_service_name or "",
                xhttp_path=server.xhttp_path or "/xhttp",
                xhttp_mode=server.xhttp_mode or "auto",
                xhttp_host=server.xhttp_host or "",
                fingerprint=server.fingerprint or "chrome",
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
    """Base64-подписка для v2rayNG/Streisand/Happ."""
    links = get_user_links(email)
    raw = "\n".join(l.link for l in links)
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return encoded