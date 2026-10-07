# main.py
from __future__ import annotations

import sys
import io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import typer
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from cli import server_commands  # noqa: E402
from cli import sub_commands     # noqa: E402
from cli import serve_commands   # noqa: E402
from cli import user_commands    # noqa: E402

app = typer.Typer(
    name="xray-manager",
    help="Управление Xray (VLESS+Reality) и подписками",
    no_args_is_help=False,  # ← отключим автопомощь, чтобы открывать меню
    add_completion=False,
)

app.add_typer(server_commands.app, name="server")
app.add_typer(sub_commands.app, name="sub")
app.add_typer(serve_commands.app, name="serve")
app.add_typer(user_commands.app, name="user")


@app.command("menu")
def menu_cmd():
    """Открыть интерактивное меню."""
    from cli.menu import run_menu
    run_menu()


def _run_interactive_menu() -> None:
    from cli.menu import run_menu
    run_menu()


if __name__ == "__main__":
    # Если запустили без аргументов — открываем меню
    if len(sys.argv) == 1:
        _run_interactive_menu()
    else:
        app()