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

            # Проверяем, нет ли уже связи
            existing_link = (
                session.query(UserServer)
                .filter_by(user_id=user.id, server_id=server.id)
                .one_or_none()
            )
            if existing_link:
                continue

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

        if state == "empty":
            # 1. Установка Xray (полный цикл)
            log("[1/4] Устанавливаю Xray...")
            install_xray(ssh, log_callback=log)
        elif state == "installed_no_config":
            # Xray уже есть, но конфига нет — пропускаем установку
            log("[1/4] Xray уже установлен, пропускаю установку.")
        elif state == "installed_with_config":
            # Уже полностью настроен — предупреждаем, но не падаем
            log("[WARN] Xray уже настроен. Конфиг будет перезаписан.")
        else:
            raise ImportError_(f"Неизвестное состояние сервера: {state}")

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

def get_server_status(server_id: int) -> dict:
    """
    Проверяет состояние Xray на сервере:
    - установлен ли бинарник
    - активна ли служба
    - версия
    - uptime
    - кол-во клиентов в конфиге
    """
    session = get_session()
    try:
        server = session.query(Server).filter_by(id=server_id).one_or_none()
        if not server:
            raise ImportError_(f"Сервер с id={server_id} не найден.")
    finally:
        session.close()

    ssh = XrayServer(
        host=server.host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        key_path=server.ssh_key_path,
    )

    result = {
        "server_id": server.id,
        "name": server.name,
        "host": server.host,
        "port": server.xray_port,
        "xray_installed": False,
        "service_active": "unknown",
        "version": "unknown",
        "uptime": "unknown",
        "clients_count": 0,
        "config_ok": False,
        "error": None,
    }

    try:
        with ssh.session():
            # 1. Установлен ли Xray
            result["xray_installed"] = ssh.xray_installed()
            if not result["xray_installed"]:
                result["error"] = "Xray не установлен"
                return result

            # 2. Статус службы
            result["service_active"] = ssh.xray_service_status_sudo()

            # 3. Версия Xray
            ver = ssh.run("/usr/local/bin/xray version", warn=True)
            if ver.ok:
                # Xray version: 25.3.6 (...)
                first_line = (ver.stdout or "").splitlines()[0] if ver.stdout else ""
                # Извлекаем версию через split
                parts = first_line.split()
                if len(parts) >= 2:
                    result["version"] = parts[-2] if parts[-2][0].isdigit() else parts[-1]
                else:
                    result["version"] = first_line

            # 4. Uptime сервиса
            uptime = ssh.run(
                "systemctl show xray --property=ActiveEnterTimestamp --value",
                warn=True,
            )
            if uptime.ok and uptime.stdout.strip():
                result["uptime"] = uptime.stdout.strip()

            # 5. Кол-во клиентов в config.json
            try:
                config_text = ssh.read_config_auto()
                inbound = parse_config(config_text)
                result["clients_count"] = len(inbound.clients)
                result["config_ok"] = True
            except Exception as e:
                result["error"] = f"Ошибка чтения конфига: {e}"

        return result
    except Exception as e:
        result["error"] = str(e)
        return result

def edit_server(
    *,
    server_id: int,
    new_port: int | None = None,
    new_dest: str | None = None,
    new_server_names: list[str] | None = None,
) -> dict:
    """
    Меняет параметры существующего сервера:
      - порт Xray
      - dest (маскировочный сайт)
      - serverNames (SNI)

    Обновляет config.json на сервере и БД.
    Перезапускает Xray.
    """
    from core.config_parser import update_reality_settings

    session = get_session()
    try:
        server = session.query(Server).filter_by(id=server_id).one_or_none()
        if not server:
            raise ImportError_(f"Сервер с id={server_id} не найден.")

        old_port = server.xray_port
        old_dest = server.reality_dest
        old_sni = list(json.loads(server.reality_server_names or "[]"))

        ssh = XrayServer(
            host=server.host,
            ssh_port=server.ssh_port,
            ssh_user=server.ssh_user,
            key_path=server.ssh_key_path,
        )

        with ssh.session():
            # 1. Читаем текущий конфиг
            config_text = ssh.read_config_auto()

            # 2. Модифицируем
            updated = update_reality_settings(
                config_text,
                new_port=new_port,
                new_dest=new_dest,
                new_server_names=new_server_names,
            )

            # 3. Валидируем (записываем во временный файл и проверяем)
            ssh.run(
                "sudo tee /tmp/xray_test.json > /dev/null << 'EOF'\n"
                f"{updated}\nEOF",
                warn=True,
            )
            check = ssh.run(
                "sudo /usr/local/bin/xray run -test -c /tmp/xray_test.json",
                warn=True,
            )
            if check.failed:
                raise ImportError_(
                    f"Конфиг невалидный:\n{check.stderr}"
                )

            # 4. Записываем основной конфиг (с бэкапом)
            ssh.write_config_auto(
                "/usr/local/etc/xray/config.json",
                updated,
                backup=True,
            )

            # 5. Перезапускаем
            ssh.restart_xray()
            status = ssh.xray_service_status_sudo()
            if status != "active":
                raise ImportError_(
                    f"Xray не запустился после изменений (status={status}).\n"
                    f"Проверь: sudo journalctl -u xray -n 50"
                )

        # 6. Обновляем БД
        if new_port is not None:
            server.xray_port = int(new_port)
        if new_dest is not None:
            server.reality_dest = new_dest
        if new_server_names is not None:
            server.reality_server_names = json.dumps(list(new_server_names))

        session.commit()

        return {
            "server_id": server.id,
            "name": server.name,
            "host": server.host,
            "old_port": old_port,
            "new_port": server.xray_port,
            "old_dest": old_dest,
            "new_dest": server.reality_dest,
            "old_sni": old_sni,
            "new_sni": list(json.loads(server.reality_server_names or "[]")),
        }
    finally:
        session.close()
