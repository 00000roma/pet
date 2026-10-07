# cli/user_commands.py
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.user_manager import (
    add_user,
    remove_user,
    list_users,
    UserManagerError,
)
from db.database import init_db

app = typer.Typer(help="Управление пользователями")
console = Console()


def _parse_server_ids(raw: str) -> list[int]:
    if raw.strip().lower() == "all":
        # будет обработано внутри — «все серверы»
        from db.database import get_session
        from db.models import Server
        session = get_session()
        try:
            return [s.id for s in session.query(Server).all()]
        finally:
            session.close()
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise typer.BadParameter("Формат: 1,2,3 или 'all'")


@app.command("add")
def add_cmd(
    email: str = typer.Option(..., "--email", "-e", help="Email пользователя"),
    servers: str = typer.Option(
        ..., "--servers", "-s",
        help="ID серверов через запятую (1,2,3) или 'all'",
    ),
    flow: str = typer.Option(
        "xtls-rprx-vision", "--flow",
        help="Flow (по умолчанию xtls-rprx-vision)",
    ),
):
    """Добавить пользователя на серверы."""
    init_db()
    try:
        ids = _parse_server_ids(servers)
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if not ids:
        console.print("[yellow]Нет серверов для добавления.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Добавляю {email} на серверы: {ids}[/cyan]")

    try:
        uuid_str, results = add_user(email=email, server_ids=ids, flow=flow)
    except UserManagerError as e:
        console.print(Panel(f"[red]{e}", title="Ошибка"))
        raise typer.Exit(code=1)

    table = Table(title=f"Результат для {email}", show_lines=True)
    table.add_column("Сервер", style="cyan")
    table.add_column("Host")
    table.add_column("Статус")
    table.add_column("Сообщение")

    for r in results:
        color = "green" if r.status == "ok" else "red"
        table.add_row(r.server_name, r.host, f"[{color}]{r.status}[/{color}]", r.message)

    console.print(table)
    console.print(f"UUID: [bold]{uuid_str}[/bold]")


@app.command("remove")
def remove_cmd(
    email: str = typer.Option(..., "--email", "-e", help="Email пользователя"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение"),
):
    """Удалить пользователя со всех серверов и из БД."""
    init_db()
    if not yes:
        typer.confirm(
            f"Удалить пользователя '{email}' со всех серверов?",
            abort=True,
        )

    try:
        results = remove_user(email)
    except UserManagerError as e:
        console.print(Panel(f"[red]{e}", title="Ошибка"))
        raise typer.Exit(code=1)

    table = Table(title=f"Удаление {email}", show_lines=True)
    table.add_column("Сервер", style="cyan")
    table.add_column("Host")
    table.add_column("Статус")
    table.add_column("Сообщение")

    for r in results:
        color = "green" if r.status == "ok" else "red"
        table.add_row(r.server_name, r.host, f"[{color}]{r.status}[/{color}]", r.message)

    console.print(table)


@app.command("list")
def list_cmd():
    """Показать всех пользователей и их серверы."""
    init_db()
    users = list_users()
    if not users:
        console.print("[yellow]Пользователей пока нет.[/yellow]")
        return

    table = Table(title="Пользователи", show_lines=True)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Email")
    table.add_column("UUID")
    table.add_column("Серверы")

    for u in users:
        servers_str = ", ".join(
            f"{s['name']}({s['host']})" for s in u["servers"]
        ) or "[dim]нет[/dim]"
        table.add_row(str(u["id"]), u["email"], u["uuid"][:16] + "...", servers_str)

    console.print(table)