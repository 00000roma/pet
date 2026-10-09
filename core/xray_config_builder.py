# core/xray_config_builder.py
"""
Сборка полного JSON-конфига Xray для клиента.
Включает inbounds (SOCKS+HTTP), outbounds (VLESS+Reality+XHTTP),
routing (блокировка рекламы, direct для РФ, остальное через прокси).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from db.database import get_session
from db.models import Server, User, UserServer

import os
from pathlib import Path



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
    user_uuid, servers = _fetch_user_servers(email)

    if primary_only or len(servers) == 1:
        proxy_outbound = _build_proxy_outbound(servers[0], tag="proxy")
        outbounds = [
            proxy_outbound,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
        default_proxy_tag = "proxy"
    else:
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

    routing_rules = _build_routing_rules(default_proxy_tag=default_proxy_tag)

    return {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": [
                "1.1.1.1",
                "8.8.8.8",
                {"address": "localhost", "domains": ["geosite:private"]},
            ]
        },
        "inbounds": _build_inbounds(),
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules,
        },
    }


def build_client_config_json(email: str, primary_only: bool = True) -> str:
    """Возвращает JSON-строку клиентского конфига."""
    config = build_client_config(email, primary_only=primary_only)
    return json.dumps(config, indent=2, ensure_ascii=False)

CUSTOM_ROUTING_PATH = Path(
    os.getenv("CUSTOM_ROUTING_PATH", "data/routing_custom.json")
)


def _load_custom_routing() -> dict:
    """
    Читает пользовательские правила из файла.
    Если файла нет — возвращает пустую структуру.
    """
    empty = {
        "direct_domains": [],
        "direct_ips": [],
        "block_domains": [],
        "block_ips": [],
        "proxy_domains": [],
        "proxy_ips": [],
    }
    if not CUSTOM_ROUTING_PATH.exists():
        return empty

    try:
        with CUSTOM_ROUTING_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return empty

    # Объединяем с пустой структурой, чтобы все ключи были
    for key in empty:
        if key not in data or not isinstance(data[key], list):
            data[key] = []
    return data

class ConfigBuildError(Exception):
    pass


def _build_routing_rules(default_proxy_tag: str = "proxy") -> list[dict]:
    """
    Собирает список правил маршрутизации:
    1. Кастомные правила из файла (блок → direct → proxy)
    2. Стандартные: реклама, локальные, РФ, CN
    3. Финал: всё остальное → proxy
    """
    custom = _load_custom_routing()
    rules: list[dict] = []

    # 1. Кастомные блокировки
    if custom["block_domains"] or custom["block_ips"]:
        rule = {"type": "field", "outboundTag": "block"}
        if custom["block_domains"]:
            rule["domain"] = custom["block_domains"]
        if custom["block_ips"]:
            rule["ip"] = custom["block_ips"]
        rules.append(rule)

    # 2. Кастомные direct
    if custom["direct_domains"] or custom["direct_ips"]:
        rule = {"type": "field", "outboundTag": "direct"}
        if custom["direct_domains"]:
            rule["domain"] = custom["direct_domains"]
        if custom["direct_ips"]:
            rule["ip"] = custom["direct_ips"]
        rules.append(rule)

    # 3. Кастомные принудительные proxy
    if custom["proxy_domains"] or custom["proxy_ips"]:
        rule = {"type": "field", "outboundTag": default_proxy_tag}
        if custom["proxy_domains"]:
            rule["domain"] = custom["proxy_domains"]
        if custom["proxy_ips"]:
            rule["ip"] = custom["proxy_ips"]
        rules.append(rule)

    # 4. Стандартные правила
    rules.extend([
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
    ])

    # 5. Финал: всё остальное через прокси
    rules.append({
        "type": "field",
        "network": "tcp,udp",
        "outboundTag": default_proxy_tag,
    })

    return rules
