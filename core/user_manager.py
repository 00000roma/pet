# core/user_manager.py
from __future__ import annotations
import secrets
import uuid
from dataclasses import dataclass

from core.ssh_client import XrayServer, SSHError
from core.config_parser import add_client, remove_client
from db.database import get_session
from db.models import Server, User, UserServer


class UserManagerError(Exception):
    pass


@dataclass
class ActionResult:
    server_name: str
    host: str
    status: str  # "ok" | "error"
    message: str = ""


def _get_server(server_id: int) -> Server:
    session = get_session()
    try:
        server = session.query(Server).filter_by(id=server_id).one_or_none()
        if not server:
            raise UserManagerError(f"Сервер с id={server_id} не найден.")
        return server
    finally:
        session.close()


def _sync_user_to_server(server, user_uuid, email, flow=""):
    if not server.managed:
        raise UserManagerError(
            f"Сервер '{server.name}' импортирован (не управляется). "
            f"Изменения конфига запрещены. "
            f"Если нужно управлять — переключи в режим 'managed' в меню серверов."
        )
    ssh = XrayServer(
        host=server.host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        key_path=server.ssh_key_path,        # ← ТУТ ЧТО?
    )

    with ssh.session():
        config_text = ssh.read_config_auto()
        updated = add_client(config_text, uuid=user_uuid, email=email, flow=flow)
        ssh.write_config_auto("/usr/local/etc/xray/config.json", updated, backup=True)
        ssh.restart_xray()


def _remove_user_from_server(server: Server, email: str) -> None:
    """Удаляет пользователя из config.json и перезапускает Xray."""
    if not server.managed:
        raise UserManagerError(
            f"Сервер '{server.name}' импортирован (не управляется). "
            f"Изменения конфига запрещены. "
            f"Если нужно управлять — переключи в режим 'managed' в меню серверов."
        )
    ssh = XrayServer(
        host=server.host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        key_path=server.ssh_key_path,
    )
    with ssh.session():
        config_text = ssh.read_config_auto()
        updated = remove_client(config_text, email=email)
        ssh.write_config_auto(
            "/usr/local/etc/xray/config.json",
            updated,
            backup=True,
        )
        ssh.restart_xray()


def add_user(
    email: str,
    server_ids: list[int],
    flow: str = "",
) -> tuple[str, list[ActionResult]]:
    """
    Создаёт (или берёт существующего) пользователя и добавляет на указанные серверы.

    Возвращает:
      - uuid созданного/найденного пользователя
      - список результатов по каждому серверу
    """
    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if not user:
            user = User(
                uuid=str(uuid.uuid4()),
                email=email,
                token=secrets.token_urlsafe(24),    # ← НОВОЕ
            )
            session.add(user)
            session.flush()
            session.commit()
    finally:
        session.close()

    results: list[ActionResult] = []

    for sid in server_ids:
        try:
            server = _get_server(sid)
        except UserManagerError as e:
            results.append(ActionResult("?", "?", "error", str(e)))
            continue

        # Генерируем UUID ДЛЯ ЭТОГО СЕРВЕРА ДО вызова sync
        server_uuid = str(uuid.uuid4())

        try:
            _sync_user_to_server(
                server=server,
                user_uuid=server_uuid,          # ← UUID для этого сервера
                email=user.email,
                flow=flow,
            )
            
            # сохраняем связь в БД
            session = get_session()
            try:
                exists = (
                    session.query(UserServer)
                    .filter_by(user_id=user.id, server_id=server.id)
                    .one_or_none()
                )
                if not exists:
                    session.add(
                        UserServer(
                            user_id=user.id,
                            server_id=server.id,
                            uuid=server_uuid,       # ← тот же UUID
                            flow=flow,
                        )
                    )
                    session.commit()
            finally:
                session.close()

            results.append(
                ActionResult(server.name, server.host, "ok", "добавлен")
            )
        except (SSHError, Exception) as e:
            results.append(
                ActionResult(server.name, server.host, "error", str(e))
            )

    return user.uuid, results


def remove_user(email: str) -> list[ActionResult]:
    """Удаляет пользователя со всех серверов и из БД."""
    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if not user:
            raise UserManagerError(f"Пользователь '{email}' не найден.")

        # Находим все серверы, где есть этот пользователь
        rows = (
            session.query(Server)
            .join(UserServer, UserServer.server_id == Server.id)
            .filter(UserServer.user_id == user.id)
            .all()
        )
        servers = list(rows)
        user_uuid = user.uuid
        user_id = user.id
    finally:
        session.close()

    results: list[ActionResult] = []

    for server in servers:
        try:
            _remove_user_from_server(server, email)
            results.append(
                ActionResult(server.name, server.host, "ok", "удалён")
            )
        except (SSHError, Exception) as e:
            results.append(
                ActionResult(server.name, server.host, "error", str(e))
            )

    # Удаляем из БД (даже если где-то была ошибка — юзер не нужен)
    session = get_session()
    try:
        session.query(UserServer).filter_by(user_id=user_id).delete()
        session.query(User).filter_by(id=user_id).delete()
        session.commit()
    finally:
        session.close()

    return results


def list_users() -> list[dict]:
    """Возвращает всех пользователей и их серверы."""
    session = get_session()
    try:
        users = session.query(User).order_by(User.id).all()
        result = []
        for user in users:
            rows = (
                session.query(Server)
                .join(UserServer, UserServer.server_id == Server.id)
                .filter(UserServer.user_id == user.id)
                .all()
            )
            result.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "uuid": user.uuid,
                    "servers": [
                        {"id": s.id, "name": s.name, "host": s.host}
                        for s in rows
                    ],
                }
            )
        return result
    finally:
        session.close()

def _sync_users_batch(
    server: Server,
    users: list[dict],
) -> list[ActionResult]:
    """
    Добавляет МНОГО пользователей в config.json сервера за ОДИН SSH-сеанс.
    Xray перезагружается ТОЛЬКО ОДИН РАЗ в конце.

    users — список словарей {"uuid": str, "email": str, "flow": str}
    """
    if not server.managed:
        raise UserManagerError(
            f"Сервер '{server.name}' импортирован (не управляется). "
            f"Изменения конфига запрещены."
        )

    if not users:
        return []

    results: list[ActionResult] = []

    ssh = XrayServer(
        host=server.host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        key_path=server.ssh_key_path,
    )

    with ssh.session():
        # 1. Читаем config ОДИН раз
        config_text = ssh.read_config_auto()

        # 2. Добавляем всех пользователей в память
        updated = config_text
        added_count = 0
        skipped_count = 0

        for u in users:
            uuid = u["uuid"]
            email = u["email"]
            flow = u.get("flow", "")

            try:
                new_config = add_client(updated, uuid=uuid, email=email, flow=flow)
                if new_config != updated:
                    added_count += 1
                else:
                    skipped_count += 1
                updated = new_config
            except Exception as e:
                results.append(ActionResult(
                    server.name, server.host, "error",
                    f"{email}: {e}"
                ))

        # 3. Записываем config ОДИН раз
        if added_count > 0:
            ssh.write_config_auto(
                "/usr/local/etc/xray/config.json",
                updated,
                backup=True,
            )

            # 4. Перезагружаем Xray ОДИН раз
            ssh.restart_xray()

            status = ssh.xray_service_status_sudo()
            if status != "active":
                raise UserManagerError(
                    f"Xray не запустился после добавления: статус={status}"
                )

        # 5. Формируем результат для каждого пользователя
        for u in users:
            email = u["email"]
            # Если для этого email уже была ошибка — пропускаем
            if any(r.status == "error" and email in r.message for r in results):
                continue

            results.append(ActionResult(
                server.name, server.host, "ok",
                f"добавлен" if added_count > 0 else "уже есть",
            ))

    return results