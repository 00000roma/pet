# core/installer.py
from __future__ import annotations

from core.ssh_client import XrayServer, SSHError


class InstallError(Exception):
    pass


# URL для скачивания готового бинарника Xray
XRAY_ZIP_URL = (
    "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
)

# Куда ставим бинарник (стандартный путь Xray)
XRAY_BIN_PATH = "/usr/local/bin/xray"
XRAY_SHARE_DIR = "/usr/local/share/xray"
XRAY_CONFIG_DIR = "/usr/local/etc/xray"

# systemd unit для Xray (стандартный, как у официального установщика)
SYSTEMD_UNIT = """[Unit]
Description=Xray Service
Documentation=https://github.com/xtls
After=network.target nss-lookup.target

[Service]
User=nobody
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=/usr/local/bin/xray run -config /usr/local/etc/xray/config.json
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000
RuntimeDirectory=xray
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
"""


def _log(cb, msg: str) -> None:
    if cb:
        cb(msg)


def install_xray(ssh: XrayServer, log_callback=None) -> None:
    """
    Устанавливает Xray вручную через wget.

    Почему не используем официальный install-release.sh:
    - В сетях с DPI внутренний curl обрывает скачивание бинарника.
    - wget в тех же условиях справляется.
    - Мы полностью контролируем процесс.
    """
    def log(msg: str) -> None:
        _log(log_callback, msg)

    # 1. Убеждаемся, что wget установлен
    log("Проверяю наличие wget...")
    check = ssh.run("which wget || echo missing", warn=True)
    if "missing" in (check.stdout or ""):
        log("wget не найден, устанавливаю...")
        result = ssh.run(
            "sudo apt-get update -qq && sudo apt-get install -y -qq wget",
            warn=True,
        )
        if result.failed:
            raise InstallError(
                f"Не удалось установить wget:\n{result.stderr}"
            )

    # 2. Проверяем, что unzip установлен
    log("Проверяю наличие unzip...")
    check = ssh.run("which unzip || echo missing", warn=True)
    if "missing" in (check.stdout or ""):
        log("unzip не найден, устанавливаю...")
        result = ssh.run(
            "sudo apt-get install -y -qq unzip",
            warn=True,
        )
        if result.failed:
            raise InstallError(
                f"Не удалось установить unzip:\n{result.stderr}"
            )

    # 3. Скачиваем Xray через wget
    log("Скачиваю Xray (21 МБ, может занять минуту)...")
    download_cmd = (
        f"wget --tries=5 --timeout=30 --no-check-certificate "
        f"-O /tmp/xray.zip {XRAY_ZIP_URL}"
    )
    result = ssh.run(download_cmd, hide=False, warn=True)
    if result.failed:
        raise InstallError(
            f"Не удалось скачать Xray.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    # Проверяем размер
    check = ssh.run("stat -c %s /tmp/xray.zip", warn=True)
    size = int((check.stdout or "0").strip() or "0")
    if size < 10_000_000:  # меньше 10 МБ — что-то не так
        raise InstallError(
            f"Скачанный файл слишком маленький ({size} байт). "
            f"Возможно, скачивание не завершилось."
        )
    log(f"    Скачано: {size // 1024 // 1024} МБ")

    # 4. Распаковываем и устанавливаем
    log("Распаковываю и устанавливаю...")
    cmds = [
        "rm -rf /tmp/xray_extract",
        "mkdir -p /tmp/xray_extract",
        "unzip -o /tmp/xray.zip -d /tmp/xray_extract",
        f"sudo mkdir -p {XRAY_SHARE_DIR} {XRAY_CONFIG_DIR}",
        f"sudo mv /tmp/xray_extract/xray {XRAY_BIN_PATH}",
        f"sudo chmod +x {XRAY_BIN_PATH}",
        # geoip/geosite — опционально, но полезно
        f"sudo mv /tmp/xray_extract/geoip.dat {XRAY_SHARE_DIR}/ 2>/dev/null || true",
        f"sudo mv /tmp/xray_extract/geosite.dat {XRAY_SHARE_DIR}/ 2>/dev/null || true",
        "rm -rf /tmp/xray_extract /tmp/xray.zip",
    ]
    for c in cmds:
        result = ssh.run(c, warn=True)
        if result.failed:
            raise InstallError(f"Команда провалилась: {c}\n{result.stderr}")

    # 5. Создаём systemd unit
    log("Создаю systemd-юнит...")
    # Записываем unit-файл через base64, чтобы избежать проблем с кавычками
    import base64
    encoded = base64.b64encode(SYSTEMD_UNIT.encode()).decode()
    ssh.run(
        f"echo '{encoded}' | base64 -d | sudo tee /etc/systemd/system/xray.service > /dev/null"
    )
    ssh.run("sudo systemctl daemon-reload")
    ssh.run("sudo systemctl enable xray", warn=True)

    # 6. Проверяем, что бинарник работает
    log("Проверяю бинарник...")
    check = ssh.run(f"{XRAY_BIN_PATH} version", warn=True)
    if check.failed:
        raise InstallError(
            f"Xray установлен, но не запускается:\n{check.stderr}"
        )
    version_line = (check.stdout or "").splitlines()[0] if check.stdout else "?"
    log(f"    {version_line}")

    if not ssh.xray_installed():
        raise InstallError(f"Бинарник не найден по пути {XRAY_BIN_PATH}")

    log("Xray успешно установлен.")