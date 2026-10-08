# core/xray_config_builder.py
"""
Сборка полного JSON-конфига Xray для клиента.

Включает:
- inbounds (SOCKS + HTTP) для локальных приложений
- outbounds (VLESS+Reality+XHTTP для каждого сервера пользователя)
- routing (правила маршрутизации: реклама, локалка, РФ)
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from db.database import get_session
from db.models import Server, User, UserServer


class ConfigBuildError(Exception):
    pass


# ---------- Правила маршрутизации по умолчанию ----------

DEFAULT_ROUTING_RULES = [
    {
        "type": "field",
        "domain": ["geosite:category-ads-all"],
        "outboundTag": "block",
    },
    {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "direct",
    },
    {
        "type": "field",
        "domain": [
            "geosite:category-gov-ru",
            "geosite:cn",
            "geosite:private",
        ],
        "outboundTag": "direct",
    },
    {
        "type": "field",
        "ip": ["geoip:ru", "geoip:cn"],
        "outboundTag": "direct",
    },
]


@dataclass
class _UserServerInfo:
    server_id: int
    server_name: str
    host: str
    port: int
    uuid: str
    email: str
    public_key: str
    sni: str
    short_id: str
    path: str = "/xhttp"
    mode: str = "auto"
    fingerprint: str = "chrome"
    spider_x: str = "/"
    network: str = "xhttp"
    security: str = "reality"


def _fetch_user_servers(email: str) -> tuple[str, list[_UserServerInfo]]:
    """Возвращает UUID пользователя и список серверов с параметрами."""
    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if not user:
            raise ConfigBuildError(f"Пользователь '{email}' не найден.")

        rows = (
            session.query(UserServer, Server)
            .join(Server, UserServer.server_id == Server.id)
            .filter(UserServer.user_id == user.id)
            .order_by(Server.id)
            .all()
        )
        if not rows:
            raise ConfigBuildError(f"У пользователя '{email}' нет серверов.")

        result: list[_UserServerInfo] = []
        for _, server in rows:
            server_names = json.loads(server.reality_server_names or "[]")
            short_ids = json.loads(server.reality_short_ids or "[]")
            if not server_names or not short_ids:
                continue

            result.append(
                _UserServerInfo(
                    server_id=server.id,
                    server_name=server.name,
                    host=server.host,
                    port=server.xray_port,
                    uuid=user.uuid,
                    email=user.email,
                    public_key=server.reality_public_key,
                    sni=server_names[0],
                    short_id=short_ids[0],
                )
            )

        if not result:
            raise ConfigBuildError(
                f"У '{email}' нет серверов с валидными Reality-параметрами."
            )
        return user.uuid, result
    finally:
        session.close()


def _build_inbounds() -> list[dict]:
    """Локальные inbounds: SOCKS и HTTP."""
    return [
        {
            "tag": "socks-in",
            "port": 10808,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True},
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
            },
        },
        {
            "tag": "http-in",
            "port": 10809,
            "listen": "127.0.0.1",
            "protocol": "http",
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
            },
        },
    ]


def _build_proxy_outbound(info: _UserServerInfo, tag: str) -> dict:
    """Собирает outbound для одного сервера."""
    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": info.host,
                    "port": info.port,
                    "users": [
                        {
                            "id": info.uuid,
                            "email": info.email,
                            "encryption": "none",
                            # flow не указываем — XHTTP не поддерживает
                        }
                    ],
                }
            ]
        },
        "streamSettings": {
            "network": info.network,
            "security": info.security,
            "realitySettings": {
                "show": False,
                "serverName": info.sni,
                "publicKey": info.public_key,
                "shortId": info.short_id,
                "fingerprint": info.fingerprint,
                "spiderX": info.spider_x,
            },
            "xhttpSettings": {
                "path": info.path,
                "mode": info.mode,
            },
        },
    }


def build_client_config(email: str, primary_only: bool = True) -> dict:
    """
    Собирает полный клиентский конфиг Xray.

    primary_only=True — использовать только первый (основной) сервер.
    primary_only=False — все серверы пользователя + selector для выбора.
    """
    user_uuid, servers = _fetch_user_servers(email)

    if primary_only or len(servers) == 1:
        # Один сервер — простой конфиг
        proxy_outbound = _build_proxy_outbound(servers[0], tag="proxy")
        outbounds = [
            proxy_outbound,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
        default_proxy_tag = "proxy"
    else:
        # Несколько серверов — selector
        proxy_outbounds = [
            _build_proxy_outbound(srv, tag=f"proxy-{i+1}")
            for i, srv in enumerate(servers)
        ]
        proxy_tags = [f"proxy-{i+1}" for i in range(len(servers))]
        selector = {
            "tag": "proxy",
            "protocol": "selector",
            "settings": {
                "outbounds": proxy_tags,
                "default": proxy_tags[0],
            },
        }
        outbounds = [
            *proxy_outbounds,
            selector,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
        default_proxy_tag = "proxy"

    # Финальное правило: всё остальное → proxy
    routing_rules = list(DEFAULT_ROUTING_RULES)
    routing_rules.append(
        {
            "type": "field",
            "network": "tcp,udp",
            "outboundTag": default_proxy_tag,
        }
    )

    config = {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": [
                "1.1.1.1",
                "8.8.8.8",
                {
                    "address": "localhost",
                    "domains": ["geosite:private"],
                },
            ]
        },
        "inbounds": _build_inbounds(),
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules,
        },
    }
    return config


def build_client_config_json(email: str, primary_only: bool = True) -> str:
    """Возвращает JSON-строку клиентского конфига."""
    config = build_client_config(email, primary_only=primary_only)
    return json.dumps(config, indent=2, ensure_ascii=False)