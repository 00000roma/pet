# cli/server_commands.py
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from core.server_manager import import_existing_server, ImportError_
from core.ssh_client import SSHError
from db.database import init_db, get_session
from db.models import Server

app = typer.Typer(help="Управление серверами Xray")
console = Console()


@app.command("import")
def import_cmd(
    host: str = typer.Option(..., "--host", "-h", help="IP или домен сервера"),
    key: str = typer.Option(..., "--key", "-k", help="Путь к приватному SSH-ключу"),
    ssh_port: int = typer.Option(22, "--ssh-port", help="SSH-порт"),
    ssh_user: str = typer.Option("root", "--ssh-user", help="SSH-пользователь"),
    name: str = typer.Option(None, "--name", "-n", help="Имя сервера"),
):
    """Импортировать существующий сервер с Xray (только чтение)."""
    init_db()
    try:
        with console.status(f"[cyan]Подключаюсь к {host}..."):
            summary = import_existing_server(
                host=host,
                ssh_key_path=key,
                ssh_port=ssh_port,
                ssh_user=ssh_user,
                name=name,
            )
    except (SSHError, ImportError_) as e:
        console.print(Panel(f"[red]{e}", title="Ошибка импорта"))
        raise typer.Exit(code=1)

    console.print(Panel.fit(
        f"[green]Сервер добавлен в БД[/green]\n"
        f"ID: [bold]{summary['server_id']}[/bold]\n"
        f"Имя: {summary['name']}\n"
        f"Host: {summary['host']}:{summary['port']}\n"
        f"dest: {summary['dest']}\n"
        f"SNI: {', '.join(summary['server_names'])}\n"
        f"shortIds: {', '.join(summary['short_ids'])}\n"
        f"Публичный ключ: {summary['public_key'][:20]}...\n"
        f"Импортировано пользователей: [bold]{summary['users_imported']}[/bold] "
        f"(всего на сервере: {summary['users_total_on_server']})",
        title="Импорт завершён",
    ))


@app.command("list")
def list_cmd():
    """Показать все серверы из БД."""
    init_db()
    session = get_session()
    try:
        servers = session.query(Server).order_by(Server.id).all()
        if not servers:
            console.print("[yellow]Серверов пока нет.[/yellow]")
            return

        table = Table(title="Серверы Xray", show_lines=True)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Имя")
        table.add_column("Host")
        table.add_column("Порт", justify="right")
        table.add_column("dest")
        table.add_column("SNI")
        table.add_column("Статус")

        for s in servers:
            table.add_row(
                str(s.id),
                s.name,
                s.host,
                str(s.xray_port),
                s.reality_dest,
                ", ".join(json.loads(s.reality_server_names or "[]")),
                s.status,
            )
        console.print(table)
    finally:
        session.close()