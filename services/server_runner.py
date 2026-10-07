# services/server_runner.py
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PID_FILE = Path("data/http_server.pid")
LOG_FILE = Path("data/logs/http_server.log")


def _is_process_alive(pid: int) -> bool:
    """Проверяет, жив ли процесс с указанным PID."""
    if sys.platform == "win32":
        # На Windows используем tasklist
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        # Linux/Mac: сигнал 0 не убивает, а только проверяет
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def get_server_pid() -> int | None:
    """Возвращает PID фонового HTTP-сервера или None."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    if not _is_process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def is_server_running() -> bool:
    return get_server_pid() is not None


def start_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    wait_ready: bool = True,
) -> int:
    """
    Запускает HTTP-сервер в фоне. Возвращает PID.
    Если сервер уже запущен — возвращает существующий PID.
    """
    existing = get_server_pid()
    if existing:
        return existing

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Открываем лог в режиме append
    log_fh = open(LOG_FILE, "a", encoding="utf-8")

    # Формируем команду запуска uvicorn
    cmd = [
        sys.executable, "-m", "uvicorn",
        "services.api.app:app",
        "--host", host,
        "--port", str(port),
        "--log-level", "info",
    ]

    # На Windows используем CREATE_NEW_PROCESS_GROUP, чтобы процесс
    # не убился вместе с родительским
    kwargs = {
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    PID_FILE.write_text(str(proc.pid))

    if wait_ready:
        # Ждём секунду-две, что сервер поднялся
        for _ in range(20):
            time.sleep(0.2)
            # Проверим, что процесс ещё жив
            if not _is_process_alive(proc.pid):
                PID_FILE.unlink(missing_ok=True)
                raise RuntimeError(
                    f"HTTP-сервер упал при запуске. Логи: {LOG_FILE}"
                )
            # Проверим, что порт отвечает
            try:
                import urllib.request
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=1
                ) as r:
                    if r.status == 200:
                        return proc.pid
            except Exception:
                continue
        # Не дождались — но процесс жив, вернём PID
        return proc.pid

    return proc.pid


def stop_server() -> bool:
    """Останавливает фоновый HTTP-сервер. Возвращает True, если остановлен."""
    pid = get_server_pid()
    if not pid:
        return False

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            # Ждём до 5 секунд, что процесс завершится
            for _ in range(25):
                time.sleep(0.2)
                if not _is_process_alive(pid):
                    break
            else:
                os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

    PID_FILE.unlink(missing_ok=True)
    return True


def get_server_url(host: str = "127.0.0.1", port: int = 8080) -> str:
    return f"http://{host}:{port}"


def get_log_path() -> Path:
    return LOG_FILE