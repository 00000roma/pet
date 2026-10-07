# core/ssh_client.py
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fabric import Connection
from invoke.exceptions import UnexpectedExit

XRAY_CONFIG_PATH = "/usr/local/etc/xray/config.json"
XRAY_BIN = "/usr/local/bin/xray"


class SSHError(Exception):
    """Любая ошибка SSH-соединения или удалённой команды."""


class XrayServer:
    """
    Обёртка над удалённым сервером.
    Работает по SSH-ключу, по умолчанию пользователь root.
    """

    def __init__(
        self,
        host: str,
        ssh_port: int = 22,
        ssh_user: str = "root",
        key_path: Optional[str] = None,
        connect_timeout: int = 15,
    ) -> None:
        if not key_path:
            raise SSHError("Путь к SSH-ключу обязателен (key_path).")

        key_file = Path(key_path).expanduser()
        if not key_file.exists():
            raise SSHError(f"SSH-ключ не найден: {key_file}")

        self.host = host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.key_path = str(key_file)
        self.connect_timeout = connect_timeout

        self._conn: Optional[Connection] = None

    # ---------- Соединение ----------

    def connect(self) -> None:
        try:
            self._conn = Connection(
                host=self.host,
                user=self.ssh_user,
                port=self.ssh_port,
                connect_kwargs={
                    "key_filename": self.key_path,
                    "look_for_keys": False,
                    "allow_agent": False,
                },
                connect_timeout=self.connect_timeout,
            )
            # Проверка, что соединение реально живое
            self._conn.run("echo ok", hide=True)
        except Exception as e:
            raise SSHError(f"Не удалось подключиться к {self.host}: {e}") from e

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @contextmanager
    def session(self):
        """Контекстный менеджер: сам открывает и закрывает соединение."""
        self.connect()
        try:
            yield self
        finally:
            self.close()

    # ---------- Базовые команды ----------

    def run(self, cmd: str, hide: bool = True, warn: bool = False):
        if not self._conn:
            raise SSHError("Соединение не открыто. Вызови connect() или session().")
        try:
            return self._conn.run(cmd, hide=hide, warn=warn)
        except UnexpectedExit as e:
            if warn:
                return e.result
            raise SSHError(f"Команда провалилась на {self.host}: {cmd}\n{e}") from e

    def sudo(self, cmd: str, hide: bool = True, warn: bool = False):
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        try:
            return self._conn.sudo(cmd, hide=hide, warn=warn)
        except UnexpectedExit as e:
            if warn:
                return e.result
            raise SSHError(f"sudo-команда провалилась: {cmd}\n{e}") from e

    # ---------- Файлы (SFTP) ----------

    def read_file(self, remote_path: str) -> str:
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        try:
            sftp = self._conn.sftp()
            with sftp.open(remote_path, "r") as f:
                return f.read().decode("utf-8")
        except FileNotFoundError:
            raise SSHError(f"Файл не найден: {remote_path}")
        except Exception as e:
            raise SSHError(f"Ошибка чтения {remote_path}: {e}") from e

    def write_file(self, remote_path: str, content: str, backup: bool = True) -> None:
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        try:
            if backup:
                self.run(f"cp {remote_path} {remote_path}.bak.$(date +%s)", warn=True)
            sftp = self._conn.sftp()
            with sftp.open(remote_path, "w") as f:
                f.write(content)
        except Exception as e:
            raise SSHError(f"Ошибка записи {remote_path}: {e}") from e

    # ---------- Специфика Xray ----------

    def xray_installed(self) -> bool:
        result = self.run(f"test -x {XRAY_BIN} && echo yes || echo no", warn=True)
        return "yes" in result.stdout

    def config_exists(self) -> bool:
        result = self.run(
            f"test -f {XRAY_CONFIG_PATH} && echo yes || echo no", warn=True
        )
        return "yes" in result.stdout

    def xray_service_status(self) -> str:
        result = self.run("systemctl is-active xray", warn=True)
        return result.stdout.strip()

    def detect_state(self) -> str:
        """
        Возвращает:
        - 'empty'                 — Xray не установлен
        - 'installed_no_config'   — Xray есть, но конфига нет
        - 'installed_with_config' — всё готово
        """
        if not self.xray_installed():
            return "empty"
        if not self.config_exists():
            return "installed_no_config"
        return "installed_with_config"

    def get_public_key_from_private(self, private_key: str) -> str:
        """
        Получает публичный ключ Reality из приватного.
        Поддерживает разные форматы вывода xray x25519 -i:
          - Старый:  "Public key: <key>"
          - Новый:   "Password (PublicKey): <key>"
        """
        cmd = f"{XRAY_BIN} x25519 -i {private_key}"
        result = self.run(cmd, warn=True)
        output = result.stdout or ""

        # Ищем разные возможные варианты строки с публичным ключом
        markers = [
            "Password (PublicKey):",
            "Password(PublicKey):",
            "PublicKey:",
            "Public key:",
        ]
        for line in output.splitlines():
            for marker in markers:
                if marker in line:
                    return line.split(marker, 1)[-1].strip()

        raise SSHError(
            f"Не удалось извлечь публичный ключ из вывода xray x25519:\n{output}"
        )
        # ---------- Sudo-версии для работы с root-файлами ----------

    def read_file_sudo(self, remote_path: str) -> str:
        """Читает файл через sudo cat (для файлов, доступных только root)."""
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        result = self.run(f"sudo cat {remote_path}", warn=True)
        if result.failed:
            raise SSHError(
                f"Не удалось прочитать {remote_path} через sudo:\n{result.stderr}"
            )
        return result.stdout

    def write_file_sudo(self, remote_path: str, content: str, backup: bool = True) -> None:
        """Записывает файл через sudo tee (для root-файлов)."""
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        try:
            if backup:
                self.run(
                    f"sudo cp {remote_path} {remote_path}.bak.$(date +%s)",
                    warn=True,
                )
            # Пишем через tee, чтобы избежать проблем с правами
            sftp = self._conn.sftp()
            with sftp.open("/tmp/xray_manager_tmp.json", "w") as f:
                f.write(content)
            self.run(f"sudo mv /tmp/xray_manager_tmp.json {remote_path}")
            self.run(f"sudo chmod 644 {remote_path}")
        except Exception as e:
            raise SSHError(f"Ошибка записи {remote_path} через sudo: {e}") from e

    def restart_xray(self) -> None:
        """Перезапускает службу xray через sudo."""
        result = self.run("sudo systemctl restart xray", warn=True)
        if result.failed:
            raise SSHError(f"Не удалось перезапустить xray:\n{result.stderr}")

    def xray_service_status_sudo(self) -> str:
        """Возвращает статус службы xray (active/inactive/failed)."""
        result = self.run("sudo systemctl is-active xray", warn=True)
        return (result.stdout or "").strip()

    def read_config_auto(self, remote_path: str = "/usr/local/etc/xray/config.json") -> str:
        """
        Пытается прочитать файл напрямую, если не получилось — через sudo.
        Удобно для серверов, где SSH-юзер не root.
        """
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        result = self.run(f"cat {remote_path}", warn=True)
        if result.ok:
            return result.stdout
        return self.read_file_sudo(remote_path)

    def write_config_auto(
        self, remote_path: str, content: str, backup: bool = True
    ) -> None:
        """
        Пытается записать файл напрямую, если не получилось — через sudo.
        """
        if not self._conn:
            raise SSHError("Соединение не открыто.")
        # Проверим, можем ли писать без sudo
        test = self.run(f"test -w {remote_path} && echo yes || echo no", warn=True)
        if "yes" in (test.stdout or ""):
            self.write_file(remote_path, content, backup=backup)
        else:
            self.write_file_sudo(remote_path, content, backup=backup)