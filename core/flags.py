# core/flags.py
from __future__ import annotations


def get_flag_for_server(server_name: str) -> str:
    """
    Возвращает emoji-флаг по имени сервера.
    Расширяй список — добавляй страны.
    """
    if not server_name:
        return "🌍"

    name_lower = server_name.lower()
    flags = {
        "brazil": "🇧🇷", "brasil": "🇧🇷", "бразилия": "🇧🇷",
        "germany": "🇩🇪", "германия": "🇩🇪", "fra": "🇩🇪", "de": "🇩🇪",
        "netherlands": "🇳🇱", "нидерланды": "🇳🇱", "ams": "🇳🇱", "nl": "🇳🇱",
        "finland": "🇫🇮", "финляндия": "🇫🇮", "hel": "🇫🇮", "fi": "🇫🇮",
        "usa": "🇺🇸", "сша": "🇺🇸", "us": "🇺🇸", "america": "🇺🇸",
        "france": "🇫🇷", "франция": "🇫🇷", "fr": "🇫🇷",
        "russia": "🇷🇺", "россия": "🇷🇺", "ru": "🇷🇺", "msk": "🇷🇺",
        "uk": "🇬🇧", "gb": "🇬🇧", "london": "🇬🇧", "britain": "🇬🇧",
        "japan": "🇯🇵", "jp": "🇯🇵", "tokyo": "🇯🇵", "япония": "🇯🇵",
        "poland": "🇵🇱", "pl": "🇵🇱", "warsaw": "🇵🇱", "польша": "🇵🇱",
        "turkey": "🇹🇷", "tr": "🇹🇷", "istanbul": "🇹🇷", "турция": "🇹🇷",
        "sweden": "🇸🇪", "se": "🇸🇪", "stockholm": "🇸🇪", "швеция": "🇸🇪",
        "switzerland": "🇨🇭", "ch": "🇨🇭", "zurich": "🇨🇭", "швейцария": "🇨🇭",
        "austria": "🇦🇹", "at": "🇦🇹", "vienna": "🇦🇹", "австрия": "🇦🇹",
        "italy": "🇮🇹", "it": "🇮🇹", "rome": "🇮🇹", "италия": "🇮🇹",
        "spain": "🇪🇸", "es": "🇪🇸", "madrid": "🇪🇸", "испания": "🇪🇸",
        "canada": "🇨🇦", "ca": "🇨🇦", "канада": "🇨🇦",
        "australia": "🇦🇺", "au": "🇦🇺", "австралия": "🇦🇺",
        "india": "🇮🇳", "in": "🇮🇳", "индия": "🇮🇳",
        "china": "🇨🇳", "cn": "🇨🇳", "китай": "🇨🇳",
        "korea": "🇰🇷", "kr": "🇰🇷", "корея": "🇰🇷",
        "singapore": "🇸🇬", "sg": "🇸🇬", "сингапур": "🇸🇬",
        "hongkong": "🇭🇰", "hk": "🇭🇰", "гонконг": "🇭🇰",
        "uae": "🇦🇪", "ae": "🇦🇪", "dubai": "🇦🇪", "оаэ": "🇦🇪",
    }
    for key, flag in flags.items():
        if key in name_lower:
            return flag
    return "🌍"