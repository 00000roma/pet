# core/xray_config_builder.py
"""
Сборка полного JSON-конфига Xray для клиента.
Включает inbounds (SOCKS+HTTP), outbounds (VLESS+Reality+XHTTP),
routing (блокировка рекламы, direct для РФ, остальное через прокси).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from core.flags import get_flag_for_server
from db.database import get_session
from db.models import Server, User, UserServer


class ConfigBuildError(Exception):
    pass


# ---------- Данные ----------

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
    network: str = "xhttp"          # ← xhttp | grpc
    grpc_service_name: str = ""     # ← для gRPC
    xhttp_path: str = "/xhttp"      # ← для XHTTP
    xhttp_mode: str = "auto"        # ← для XHTTP
    fingerprint: str = "chrome"
    spider_x: str = "/"
    security: str = "reality"

# ---------- Загрузка пользователей и серверов ----------

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
        for link_row, server in rows:
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
                    uuid=link_row.uuid,
                    email=user.email,
                    public_key=server.reality_public_key,
                    sni=server_names[0],
                    short_id=short_ids[0],
                    network=server.network or "xhttp",
                    grpc_service_name=server.grpc_service_name or "",
                    xhttp_path=server.xhttp_path or "/xhttp",
                    xhttp_mode=server.xhttp_mode or "auto",
                )
            )
        if not result:
            raise ConfigBuildError(
                f"У '{email}' нет серверов с валидными Reality-параметрами."
            )
        return user.uuid, result
    finally:
        session.close()


# ---------- Inbounds ----------

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


# ---------- Outbounds ----------

def _build_proxy_outbound(info: _UserServerInfo, tag: str) -> dict:
    flag = get_flag_for_server(info.server_name)

    # Базовый streamSettings (общий для xhttp и grpc)
    stream_settings: dict = {
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
    }

    # Транспорт — XHTTP или gRPC
    if info.network == "xhttp":
        stream_settings["xhttpSettings"] = {
            "path": info.xhttp_path,
            "mode": info.xhttp_mode,
        }
    elif info.network == "grpc":
        stream_settings["grpcSettings"] = {
            "serviceName": info.grpc_service_name,
        }

    return {
        "tag": tag,
        "protocol": "vless",
        "remarks": f"{flag} {info.server_name} | {info.email}",
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
        "streamSettings": stream_settings,
    }

# ---------- Кастомные правила ----------

logger = logging.getLogger(__name__)

CUSTOM_ROUTING_PATH = Path(
    os.getenv("CUSTOM_ROUTING_PATH", "data/routing_custom.json")
)


def _load_custom_routing() -> dict:
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
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Не удалось прочитать %s: %s. Использую пустые правила.",
            CUSTOM_ROUTING_PATH, e,
        )
        return empty

    if not isinstance(data, dict):
        logger.warning(
            "%s должен быть JSON-объектом. Использую пустые правила.",
            CUSTOM_ROUTING_PATH,
        )
        return empty

    for key in empty:
        if key not in data or not isinstance(data[key], list):
            logger.warning(
                "В %s ключ '%s' отсутствует или не является списком — "
                "для него использую пустой список.",
                CUSTOM_ROUTING_PATH, key,
            )
            data[key] = []
    return data


def _build_routing_rules(default_proxy_tag: str = "proxy") -> list[dict]:
    """
    Собирает правила маршрутизации.

    Порядок обработки: proxy → direct → block → (остальное через proxy).
    Xray применяет правила сверху вниз, поэтому принудительный proxy
    имеет приоритет над direct, а direct — над block.

    ВАЖНО: Xray применяет логическое И, если в правиле и domain, и ip.
    Поэтому ВСЕГДА разделяем их на отдельные правила.
    """
    custom = _load_custom_routing()
    rules: list[dict] = []

    # 1. Прокси (высший приоритет) — принудительно через VPN
    if custom["proxy_domains"]:
        rules.append({
            "type": "field",
            "outboundTag": default_proxy_tag,
            "domain": custom["proxy_domains"],
        })
    if custom["proxy_ips"]:
        rules.append({
            "type": "field",
            "outboundTag": default_proxy_tag,
            "ip": custom["proxy_ips"],
        })

    # 2. Direct — кастомные + стандартные
    if custom["direct_domains"]:
        rules.append({
            "type": "field",
            "outboundTag": "direct",
            "domain": custom["direct_domains"],
        })
    if custom["direct_ips"]:
        rules.append({
            "type": "field",
            "outboundTag": "direct",
            "ip": custom["direct_ips"],
        })
    rules.append({
        "type": "field",
        "outboundTag": "direct",
        "ip": ["geoip:private"],
    })
    rules.append({
        "type": "field",
        "outboundTag": "direct",
        "domain": [
            "geosite:category-gov-ru",
            "geosite:cn",
            "geosite:private",
        ],
    })
    rules.append({
        "type": "field",
        "outboundTag": "direct",
        "ip": ["geoip:ru", "geoip:cn"],
    })

    # 3. Block — кастомные + стандартные (реклама)
    if custom["block_domains"]:
        rules.append({
            "type": "field",
            "outboundTag": "block",
            "domain": custom["block_domains"],
        })
    if custom["block_ips"]:
        rules.append({
            "type": "field",
            "outboundTag": "block",
            "ip": custom["block_ips"],
        })
    rules.append({
        "type": "field",
        "outboundTag": "block",
        "domain": ["geosite:category-ads-all"],
    })

    # 4. Финал — всё остальное через proxy
    rules.append({
        "type": "field",
        "network": "tcp,udp",
        "outboundTag": default_proxy_tag,
    })

    return rules


# ---------- Основная сборка ----------

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