# core/config_parser.py
from __future__ import annotations

import json
import copy
from dataclasses import dataclass, field


@dataclass
class RealityInbound:
    """Разобранные данные о VLESS+Reality inbound."""
    port: int
    dest: str
    server_names: list[str]
    private_key: str
    short_ids: list[str]
    flow: str
    clients: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class ConfigError(Exception):
    pass


def parse_config(config_text: str) -> RealityInbound:
    """
    Читает config.json и достаёт Reality-inbound (VLESS+Reality+TCP+Vision).
    Если такого inbound нет — бросает ConfigError.
    """
    try:
        data = json.loads(config_text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Некорректный JSON: {e}") from e

    inbounds = data.get("inbounds") or []
    for inbound in inbounds:
        if inbound.get("protocol") != "vless":
            continue

        stream = inbound.get("streamSettings", {}) or {}
        if stream.get("security") != "reality":
            continue

        reality = stream.get("realitySettings", {}) or {}
        settings = inbound.get("settings", {}) or {}
        clients = settings.get("clients", []) or []

        flow = "xtls-rprx-vision"
        if clients and clients[0].get("flow"):
            flow = clients[0]["flow"]

        return RealityInbound(
            port=int(inbound.get("port", 443)),
            dest=reality.get("dest", ""),
            server_names=list(reality.get("serverNames", []) or []),
            private_key=reality.get("privateKey", ""),
            short_ids=list(reality.get("shortIds", []) or []),
            flow=flow,
            clients=copy.deepcopy(clients),
            raw=copy.deepcopy(inbound),
        )

    raise ConfigError("VLESS + Reality inbound не найден в config.json")


def _find_vless_reality_inbound(data: dict) -> dict:
    for inbound in data.get("inbounds", []):
        if inbound.get("protocol") != "vless":
            continue
        if (inbound.get("streamSettings") or {}).get("security") == "reality":
            return inbound
    raise ConfigError("VLESS + Reality inbound не найден")


def add_client(config_text: str, uuid: str, email: str, flow: str = "xtls-rprx-vision") -> str:
    """Добавляет нового клиента. Если email уже есть — ничего не меняет."""
    data = json.loads(config_text)
    inbound = _find_vless_reality_inbound(data)
    clients = inbound.setdefault("settings", {}).setdefault("clients", [])

    for c in clients:
        if c.get("email") == email:
            return json.dumps(data, indent=2, ensure_ascii=False)

    clients.append({"id": uuid, "email": email, "flow": flow})
    return json.dumps(data, indent=2, ensure_ascii=False)


def remove_client(config_text: str, email: str) -> str:
    """Удаляет клиента по email."""
    data = json.loads(config_text)
    inbound = _find_vless_reality_inbound(data)
    clients = inbound.get("settings", {}).get("clients", [])
    inbound["settings"]["clients"] = [c for c in clients if c.get("email") != email]
    return json.dumps(data, indent=2, ensure_ascii=False)


def update_port(config_text: str, new_port: int) -> str:
    """Меняет порт inbound."""
    data = json.loads(config_text)
    inbound = _find_vless_reality_inbound(data)
    inbound["port"] = new_port
    return json.dumps(data, indent=2, ensure_ascii=False)