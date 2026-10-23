# core/monitoring.py
"""Мониторинг удалённого Xray-сервера: нагрузка, канал, подключения.

Собирает только нужные параметры:
  - качество соединения (пинг до сервера и пинг в интернет с сервера);
  - пропускную способность канала (тест скорости в интернет + текущий Rx/Tx);
  - нагрузку (load average, ядра CPU, память);
  - сколько пользователей сейчас подключено (активные TCP-соединения).

Всё читается через один SSH-сеанс и стандартные команды Linux,
без установки дополнительных пакетов на сервер.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from core.ssh_client import XrayServer, SSHError
from db.database import get_session
from db.models import Server

# Максимум объёма теста скорости, чтобы случайно не качать гигабайты.
SPEED_MAX_MB = 50
SPEED_DEFAULT_MB = 25

# Служебные/виртуальные интерфейсы игнорируем при выборе основного.
_IGNORED_IFACES = re.compile(
    r"^(lo|docker\d*|br-|veth|tun|tap|wg\d*|tailscale\d*|flannel|cni\d*|virbr\d*)$"
)


def _human_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _parse_loadavg(text: str):
    parts = (text or "").split()
    if len(parts) < 3:
        return None, None, None
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None, None, None


def _parse_meminfo(text: str):
    """Возвращает (total_mb, used_mb, available_mb) из /proc/meminfo."""
    total_kb = None
    available_kb = None
    for line in (text or "").splitlines():
        if line.startswith("MemTotal:"):
            m = re.search(r"\d+", line)
            if m:
                total_kb = int(m.group())
        elif line.startswith("MemAvailable:"):
            m = re.search(r"\d+", line)
            if m:
                available_kb = int(m.group())
    if total_kb is None:
        return None, None, None
    total_mb = total_kb // 1024
    available_mb = available_kb // 1024 if available_kb is not None else None
    used_mb = (total_kb - available_kb) // 1024 if available_kb is not None else None
    return total_mb, used_mb, available_mb


def _parse_ping(text: str):
    """Возвращает (min_ms, avg_ms, max_ms, loss_pct) из вывода ping."""
    loss = None
    m = re.search(r"(\d+(?:\.\d+)?)% packet loss", text or "")
    if m:
        loss = float(m.group(1))
    m = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/", text or ""
    )
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3)), loss
    return None, None, None, loss


def _read_net_dev(ssh: XrayServer) -> dict[str, tuple[int, int]]:
    """Читает /proc/net/dev → {iface: (rx_bytes, tx_bytes)}."""
    out = ssh.run("cat /proc/net/dev", warn=True)
    result: dict[str, tuple[int, int]] = {}
    for line in (out.stdout or "").splitlines()[2:]:
        if ":" not in line:
            continue
        iface, _, rest = line.partition(":")
        iface = iface.strip()
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            result[iface] = (int(parts[0]), int(parts[8]))
        except ValueError:
            continue
    return result


def _pick_iface(stats: dict[str, tuple[int, int]]) -> Optional[str]:
    candidates = {
        name: rx + tx
        for name, (rx, tx) in stats.items()
        if not _IGNORED_IFACES.match(name)
    }
    if not candidates:
        return None
    return max(candidates, key=candidates.get)


def _measure_ssh_latency(ssh: XrayServer, samples: int = 3):
    """RTT управляющего SSH-канала (min/avg/max, мс)."""
    times = []
    for _ in range(samples):
        t0 = time.perf_counter()
        ssh.run("echo ok", hide=True)
        times.append((time.perf_counter() - t0) * 1000.0)
    if not times:
        return None, None, None
    return min(times), sum(times) / len(times), max(times)


def _measure_speed(ssh: XrayServer, mb: int) -> dict:
    """Тест реальной скорости интернета сервера через CDN Cloudflare.

    Скачивает и закачивает `mb` МБ с/на speed.cloudflare.com, скорость
    считает сам curl (`%{speed_download}` / `%{speed_upload}`). Это максимум
    канала самого сервера (как speedtest), а не канал до контроллера.
    Никакие пакеты на сервер не ставятся — нужен только curl.
    """
    mb = max(0, min(int(mb), SPEED_MAX_MB))
    if mb <= 0:
        return {
            "mb": 0, "download_mbps": None, "upload_mbps": None,
            "skipped": True, "error": None,
        }

    bytes_ = mb * 1024 * 1024

    # Без curl тест невозможен.
    r = ssh.run(
        "command -v curl >/dev/null 2>&1 && echo yes || echo no",
        hide=True, warn=True,
    )
    if (r.stdout or "").strip() != "yes":
        return {
            "mb": mb, "download_mbps": None, "upload_mbps": None,
            "skipped": False, "error": "на сервере нет curl — тест скорости недоступен",
        }

    download = None
    upload = None
    errors = []

    # Download: сервер качает с Cloudflare.
    r = ssh.run(
        f"curl -s -o /dev/null -w '%{{speed_download}}' --max-time 120 "
        f"'https://speed.cloudflare.com/__down?bytes={bytes_}'",
        hide=True, warn=True,
    )
    if r.ok:
        try:
            download = float((r.stdout or "").strip()) * 8 / 1_000_000
        except ValueError:
            download = None
    else:
        errors.append((r.stderr or "").strip()[:120] or "download не удался")

    # Upload: сервер заливает на Cloudflare.
    r = ssh.run(
        f"head -c {bytes_} /dev/zero | curl -s -o /dev/null -w '%{{speed_upload}}' "
        f"--max-time 120 -X POST --data-binary @- "
        f"'https://speed.cloudflare.com/__up'",
        hide=True, warn=True,
    )
    if r.ok:
        try:
            upload = float((r.stdout or "").strip()) * 8 / 1_000_000
        except ValueError:
            upload = None
    else:
        errors.append((r.stderr or "").strip()[:120] or "upload не удался")

    error = "; ".join(errors) if errors else None
    return {
        "mb": mb, "download_mbps": download, "upload_mbps": upload,
        "skipped": False, "error": error,
    }


def _extract_ip(addr: str) -> str:
    """Вытаскивает IP из строки вида '1.2.3.4:443' или '[::1]:443'."""
    addr = addr.strip()
    if addr.startswith("["):
        end = addr.find("]")
        return addr[1:end] if end != -1 else addr
    return addr.rsplit(":", 1)[0]


def _measure_connections(ssh: XrayServer, port: int):
    """Возвращает (всего соединений, уникальных IP) на порту Xray."""
    out = ssh.run(f'ss -Htn state established "( sport = :{port} )"', warn=True)
    if out.failed or "ss:" in (out.stderr or ""):
        # Fallback на netstat (на старых системах ss может отсутствовать).
        out = ssh.run(
            f"netstat -tn 2>/dev/null | grep ESTABLISHED | grep ':{port} '",
            warn=True,
        )
    lines = [l for l in (out.stdout or "").splitlines() if l.strip()]
    if not lines:
        return 0, 0

    ips = set()
    for line in lines:
        parts = line.split()
        # В выводе ss и netstat peer-адрес — 5-я колонка (индекс 4).
        if len(parts) >= 5:
            ips.add(_extract_ip(parts[4]))
    return len(lines), len(ips)


def get_server_metrics(server_id: int, speed_mb: int = SPEED_DEFAULT_MB) -> dict:
    """Собирает метрики сервера в один SSH-сеанс.

    Возвращает словарь, пригодный для отображения в CLI/меню.
    Частичные сбои не фатальны: проблемные метрики будут None,
    а текст ошибок попадёт в поле `errors`.
    """
    session = get_session()
    try:
        server = session.query(Server).filter_by(id=server_id).one_or_none()
    finally:
        session.close()

    result: dict = {
        "server_id": server_id,
        "name": None,
        "host": None,
        "port": None,
        "service_active": "unknown",
        "uptime": None,
        "load": {"1": None, "5": None, "15": None},
        "cpu_cores": None,
        "mem": {"total_mb": None, "used_mb": None, "available_mb": None},
        "connections": {"total": None, "unique_ips": None},
        "latency_ssh": {"min": None, "avg": None, "max": None},
        "latency_internet": {
            "min": None, "avg": None, "max": None, "loss_pct": None,
        },
        "speed": {
            "mb": speed_mb, "download_mbps": None, "upload_mbps": None,
            "skipped": False, "error": None,
        },
        "net": {
            "iface": None, "rx_mbps": None, "tx_mbps": None,
            "rx_total": None, "tx_total": None,
        },
        "errors": [],
    }

    if not server:
        result["errors"].append(f"Сервер с id={server_id} не найден.")
        return result

    result["name"] = server.name
    result["host"] = server.host
    result["port"] = server.xray_port

    ssh = XrayServer(
        host=server.host,
        ssh_port=server.ssh_port,
        ssh_user=server.ssh_user,
        key_path=server.ssh_key_path,
    )

    try:
        with ssh.session():
            # Служба Xray.
            r = ssh.run("systemctl is-active xray", warn=True)
            result["service_active"] = (r.stdout or "").strip() or "unknown"

            # Uptime сервера.
            r = ssh.run("cat /proc/uptime", warn=True)
            if r.ok:
                try:
                    result["uptime"] = float((r.stdout or "").split()[0])
                except (ValueError, IndexError):
                    pass

            # Load average + ядра CPU.
            r = ssh.run("cat /proc/loadavg", warn=True)
            if r.ok:
                l1, l5, l15 = _parse_loadavg(r.stdout)
                result["load"] = {"1": l1, "5": l5, "15": l15}

            r = ssh.run("nproc", warn=True)
            if r.ok:
                try:
                    result["cpu_cores"] = int((r.stdout or "").strip())
                except ValueError:
                    pass

            # Память.
            r = ssh.run("cat /proc/meminfo", warn=True)
            if r.ok:
                total_mb, used_mb, available_mb = _parse_meminfo(r.stdout)
                result["mem"] = {
                    "total_mb": total_mb,
                    "used_mb": used_mb,
                    "available_mb": available_mb,
                }

            # Подключения.
            try:
                total, unique = _measure_connections(ssh, server.xray_port)
                result["connections"]["total"] = total
                result["connections"]["unique_ips"] = unique
            except Exception as e:  # noqa: BLE001
                result["errors"].append(f"Подключения: {e}")

            # Пинг до сервера (RTT SSH-канала).
            mn, av, mx = _measure_ssh_latency(ssh)
            result["latency_ssh"] = {"min": mn, "avg": av, "max": mx}

            # Пинг в интернет с сервера (качество канала самого сервера).
            r = ssh.run(
                "ping -c 3 -W 2 1.1.1.1 2>/dev/null || echo 'no-ping'", warn=True
            )
            if "no-ping" in (r.stdout or ""):
                result["errors"].append(
                    "На сервере нет ping (iputils-ping) — пинг в интернет недоступен."
                )
            else:
                mn, av, mx, loss = _parse_ping(r.stdout)
                result["latency_internet"] = {
                    "min": mn, "avg": av, "max": mx, "loss_pct": loss,
                }

            # Текущая загрузка канала (Rx/Tx) по основному интерфейсу.
            s1 = _read_net_dev(ssh)
            time.sleep(1.0)
            s2 = _read_net_dev(ssh)
            iface = _pick_iface(s2) or _pick_iface(s1)
            if iface:
                result["net"]["iface"] = iface
                if iface in s1 and iface in s2:
                    rx1, tx1 = s1[iface]
                    rx2, tx2 = s2[iface]
                    result["net"]["rx_total"] = _human_bytes(rx2)
                    result["net"]["tx_total"] = _human_bytes(tx2)
                    result["net"]["rx_mbps"] = max(0.0, (rx2 - rx1) * 8 / 1_000_000)
                    result["net"]["tx_mbps"] = max(0.0, (tx2 - tx1) * 8 / 1_000_000)

            # Скорость интернета сервера (тест).
            result["speed"] = _measure_speed(ssh, speed_mb)

    except SSHError as e:
        result["errors"].append(str(e))
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"Не удалось собрать метрики: {e}")

    return result
