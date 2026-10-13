# core/happ_routing.py
"""
Генерация routing-конфига для Happ (deep link).

Формат: happ://routing/add/{base64url(json)}
"""
from __future__ import annotations

import base64
import json


ROUTING_PRESETS = {
    "ru": {
        "name": "Reactive (RU)",
        "direct_sites": [
            "geosite:private",
            "geosite:category-gov-ru",
            "geosite:category-ru",
            "geosite:cn",
            "domain:rktv.ru",
        ],
        "direct_ips": [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "169.254.0.0/16",
            "224.0.0.0/4",
            "255.255.255.255",
            "geoip:private",
            "geoip:ru",
            "geoip:cn",
        ],
        "block_sites": [
            "geosite:category-ads-all",
        ],
        "block_ips": [],
        "proxy_sites": [],
        "proxy_ips": [],
        "global_proxy": "false",
    },
    "adblock": {
        "name": "Reactive (AdBlock)",
        "direct_sites": ["geosite:private"],
        "direct_ips": ["geoip:private"],
        "block_sites": ["geosite:category-ads-all"],
        "block_ips": [],
        "proxy_sites": [],
        "proxy_ips": [],
        "global_proxy": "false",
    },
    "global": {
        "name": "Reactive (Global)",
        "direct_sites": ["geosite:private"],
        "direct_ips": ["geoip:private"],
        "block_sites": ["geosite:category-ads-all"],
        "block_ips": [],
        "proxy_sites": [],
        "proxy_ips": [],
        "global_proxy": "true",
    },
}


def build_happ_routing(preset: str = "ru", custom_name: str | None = None) -> dict:
    """
    Строит routing для Happ, объединяя:
    - базовые правила пресета
    - кастомные правила из data/routing_custom.json
    """
    from core.xray_config_builder import _load_custom_routing

    if preset not in ROUTING_PRESETS:
        raise ValueError(f"Неизвестный пресет: {preset}")

    base = ROUTING_PRESETS[preset]
    custom = _load_custom_routing()

    # Объединяем базовые + кастомные правила (без дубликатов)
    def merge(a, b):
        return list(dict.fromkeys(a + b))

    direct_sites = merge(base["direct_sites"], custom.get("direct_domains", []))
    direct_ips = merge(base["direct_ips"], custom.get("direct_ips", []))
    block_sites = merge(base["block_sites"], custom.get("block_domains", []))
    block_ips = merge(base["block_ips"], custom.get("block_ips", []))

    return {
        "BlockIp": block_ips,
        "BlockSites": block_sites,
        "DirectIp": direct_ips,
        "DirectSites": direct_sites,
        "ProxyIp": custom.get("proxy_ips", []),
        "ProxySites": custom.get("proxy_domains", []),
        "DnsHosts": {
            "cloudflare-dns.com": "1.1.1.1",
            "dns.google": "8.8.8.8",
        },
        "DomainStrategy": "IPIfNonMatch",
        "DomesticDNSDomain": "https://dns.google/dns-query",
        "DomesticDNSIP": "8.8.8.8",
        "DomesticDNSType": "DoH",
        "FakeDNS": "false",
        "Geoipurl": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat",
        "Geositeurl": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
        "GlobalProxy": base["global_proxy"],
        "Name": custom_name or base["name"],
        "RemoteDNSDomain": "https://cloudflare-dns.com/dns-query",
        "RemoteDNSIP": "1.1.1.1",
        "RemoteDNSType": "DoH",
        "RouteOrder": "block-direct-proxy",
    }

def build_happ_deep_link(preset: str = "ru", custom_name: str | None = None) -> str:
    routing = build_happ_routing(preset=preset, custom_name=custom_name)
    json_str = json.dumps(routing, separators=(",", ":"), ensure_ascii=False)
    encoded = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=")
    return f"happ://routing/add/{encoded}"