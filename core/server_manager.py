# core/server_manager.py
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.ssh_client import XrayServer
from core.config_parser import parse_config
from core.reality import generate_keypair, generate_short_id
from core.installer import install_xray
from db.database import get_session
from db.models import Server, User, UserServer


class ImportError_(Exception):
    pass


# ---------- Jinja2 ----------

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render_config(
    port: int,
    dest: str,
    server_names: list[str],
    private_key: str,
    short_ids: list[str],
) -> str:
    """Рендерит config.json из шаблона templates/xray_config_base.json."""
    template = _jinja_env.get_template("xray_config_base.json")
    return template.render(
        port=port,
        dest=dest,
        server_names=server_names,
        private_key=private_key,
        short_ids=short_ids,
    )


# ---------- Импорт существующего сервера ----------

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

        config_text = srv.read_config_auto()
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


# ---------- Деплой нового сервера ----------

def deploy_fresh(
    *,
    host: str,
    ssh_key_path: str,
    ssh_port: int = 22,
    ssh_user: str = "root",
    name: str | None = None,
    xray_port: int = 443,
    dest: str = "www.microsoft.com:443",
    log_callback=None,
) -> dict:
    """
    Разворачивает Xray с нуля на чистом сервере.
    """
    name = name or host

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    ssh = XrayServer(
        host=host, ssh_port=ssh_port, ssh_user=ssh_user, key_path=ssh_key_path
    )

    with ssh.session():
        state = ssh.detect_state()
        if state != "empty":
            raise ImportError_(
                f"Сервер {host} не пустой (state={state}). "
                f"Используй 'server import' для существующего."
            )

        # 1. Установка Xray
        log("[1/4] Устанавливаю Xray...")
        install_xray(ssh, log_callback=log)

        # 2. Генерация ключей
        log("[2/4] Генерирую Reality-ключи...")
        private_key, public_key = generate_keypair(ssh)
        short_id = generate_short_id()
        log(f"    Public key: {public_key[:20]}...")
        log(f"    Short ID:   {short_id}")

        # 3. Рендер и заливка config.json
        log("[3/4] Генерирую и заливаю config.json...")
        server_names = [dest.split(":")[0]]
        config_text = _render_config(
            port=xray_port,
            dest=dest,
            server_names=server_names,
            private_key=private_key,
            short_ids=[short_id],
        )
        ssh.run("sudo mkdir -p /usr/local/etc/xray")
        ssh.write_config_auto(
            "/usr/local/etc/xray/config.json", config_text, backup=False
        )

        # 4. Запуск Xray
        log("[4/4] Запускаю службу Xray...")
        ssh.run("sudo systemctl enable xray", warn=True)
        ssh.restart_xray()

        status = ssh.xray_service_status_sudo()
        if status != "active":
            raise ImportError_(
                f"Xray не запустился. Статус: {status}. "
                f"Проверь 'sudo journalctl -u xray -n 50' на сервере."
            )

    # Сохраняем в БД
    session = get_session()
    try:
        server = Server(
            name=name,
            host=host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_key_path=ssh_key_path,
            xray_port=xray_port,
            reality_dest=dest,
            reality_server_names=json.dumps(server_names),
            reality_private_key=private_key,
            reality_public_key=public_key,
            reality_short_ids=json.dumps([short_id]),
        )
        session.add(server)
        session.commit()

        return {
            "server_id": server.id,
            "name": name,
            "host": host,
            "port": xray_port,
            "dest": dest,
            "public_key": public_key,
            "private_key": private_key,
            "short_id": short_id,
        }
    finally:
        session.close()