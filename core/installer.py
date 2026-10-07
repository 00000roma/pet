# core/installer.py
from __future__ import annotations

from core.ssh_client import XrayServer, SSHError


class InstallError(Exception):
    pass


INSTALL_SCRIPT_URL = "https://github.com/XTLS/Xray-install/raw/main/install-release.sh"


def install_xray(ssh: XrayServer, log_callback=None) -> None:
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    log("Скачиваю и запускаю официальный установщик Xray...")
    cmd = (
        f"curl -L {INSTALL_SCRIPT_URL} -o /tmp/xray-install.sh && "
        f"sudo bash /tmp/xray-install.sh install"
    )
    result = ssh.run(cmd, hide=False, warn=True)

    if result.failed:
        raise InstallError(
            f"Установка Xray провалилась.\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    if not ssh.xray_installed():
        raise InstallError("Установщик отработал, но /usr/local/bin/xray не найден.")
    log("Xray успешно установлен.")