# core/server_manager.py
from __future__ import annotations

import json

from core.ssh_client import XrayServer
from core.config_parser import parse_config
from db.database import get_session
from db.models import Server, User, UserServer


class ImportError_(Exception):
    pass


def import_existing_server(
    *,
    host: str,
    ssh_key_path: str,
    ssh_port: int = 22,
    ssh_user: str = "root",
    name: str | None = None,
) -> dict:
    """
    Подключается к уже работающему серверу, читает config.json,
    извлекает Reality-параметры и список клиентов, сохраняет всё в БД.
    """
    name = name or host

    srv = XrayServer(
        host=host, ssh_port=ssh_port, ssh_user=ssh_user, key_path=ssh_key_path
    )

    with srv.session():
        state = srv.detect_state()
        if state == "empty":
            raise ImportError_(
                f"На {host} Xray не установлен. Используй 'server add' вместо 'import'."
            )
        if state == "installed_no_config":
            raise ImportError_(f"На {host} нет config.json. Импортировать нечего.")

        config_text = srv.read_file("/usr/local/etc/xray/config.json")
        inbound = parse_config(config_text)
        public_key = srv.get_public_key_from_private(inbound.private_key)

    session = get_session()
    try:
        existing = session.query(Server).filter_by(host=host).one_or_none()
        if existing:
            raise ImportError_(f"Сервер {host} уже добавлен в БД (id={existing.id}).")

        server = Server(
            name=name,
            host=host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_key_path=ssh_key_path,
            xray_port=inbound.port,
            reality_dest=inbound.dest,
            reality_server_names=json.dumps(inbound.server_names),
            reality_private_key=inbound.private_key,
            reality_public_key=public_key,
            reality_short_ids=json.dumps(inbound.short_ids),
        )
        session.add(server)
        session.flush()

        users_added = 0
        for client in inbound.clients:
            uuid = client.get("id")
            email = client.get("email")
            flow = client.get("flow", "xtls-rprx-vision")
            if not uuid or not email:
                continue

            user = session.query(User).filter_by(email=email).one_or_none()
            if not user:
                user = User(uuid=uuid, email=email)
                session.add(user)
                session.flush()
                users_added += 1

            link = UserServer(user_id=user.id, server_id=server.id, flow=flow)
            session.add(link)

        session.commit()

        return {
            "server_id": server.id,
            "name": name,
            "host": host,
            "port": inbound.port,
            "dest": inbound.dest,
            "server_names": inbound.server_names,
            "short_ids": inbound.short_ids,
            "public_key": public_key,
            "users_imported": users_added,
            "users_total_on_server": len(inbound.clients),
        }
    finally:
        session.close()