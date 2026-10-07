# cli/server_commands.py
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from core.server_manager import (
    import_existing_server,
    deploy_fresh,
    get_server_status,
    edit_server,
    ImportError_,
)
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


@app.command("add")
def add_cmd(
    host: str = typer.Option(..., "--host", "-h", help="IP или домен сервера"),
    key: str = typer.Option(..., "--key", "-k", help="Путь к SSH-ключу"),
    ssh_port: int = typer.Option(22, "--ssh-port", help="SSH-порт"),
    ssh_user: str = typer.Option("root", "--ssh-user", help="SSH-пользователь"),
    name: str = typer.Option(None, "--name", "-n", help="Имя сервера"),
    xray_port: int = typer.Option(443, "--xray-port", help="Порт Xray"),
    dest: str = typer.Option(
        "www.microsoft.com:443", "--dest",
        help="Сайт-маскировка (dest) для Reality",
    ),
):
    """Развернуть Xray с нуля на чистом сервере."""
    init_db()

    console.print(
        Panel.fit(
            f"[yellow]ВНИМАНИЕ:[/yellow] Это установит Xray на [bold]{host}[/bold].\n"
            f"Использовать только на ЧИСТОМ сервере без Xray.",
            title="Подтверждение",
        )
    )
    if not typer.confirm("Продолжить?", default=False):
        raise typer.Exit(code=0)

    try:
        with console.status("[cyan]Разворачиваю Xray (это займёт 1-3 минуты)...[/cyan]"):
            summary = deploy_fresh(
                host=host,
                ssh_key_path=key,
                ssh_port=ssh_port,
                ssh_user=ssh_user,
                name=name,
                xray_port=xray_port,
                dest=dest,
                log_callback=None,
            )
    except (SSHError, ImportError_) as e:
        console.print(Panel(f"[red]{e}", title="Ошибка деплоя"))
        raise typer.Exit(code=1)

    console.print(Panel.fit(
        f"[green]Сервер успешно развёрнут[/green]\n"
        f"ID: [bold]{summary['server_id']}[/bold]\n"
        f"Имя: {summary['name']}\n"
        f"Host: {summary['host']}:{summary['port']}\n"
        f"dest: {summary['dest']}\n"
        f"Публичный ключ: {summary['public_key'][:30]}...\n"
        f"Short ID: {summary['short_id']}",
        title="Deploy завершён",
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

@app.command("status")
def status_cmd(
    server_id: int = typer.Option(..., "--id", help="ID сервера"),
):
    """Показать статус сервера."""
    init_db()
    try:
        with console.status(f"[cyan]Проверяю сервер id={server_id}...[/cyan]"):
            result = get_server_status(server_id)
    except Exception as e:
        console.print(Panel(f"[red]{e}", title="Ошибка"))
        raise typer.Exit(code=1)

    if result.get("error") and not result.get("xray_installed"):
        console.print(Panel(
            f"[red]Ошибка:[/red] {result['error']}",
            title=f"Сервер {result['name']}",
        ))
        return

    # Формируем таблицу
    table = Table(title=f"Статус сервера: {result['name']}", show_lines=True)
    table.add_column("Параметр", style="cyan")
    table.add_column("Значение")

    status_color = "green" if result["service_active"] == "active" else "red"
    table.add_row("Host", f"{result['host']}:{result['port']}")
    table.add_row(
        "Xray установлен",
        "[green]да[/green]" if result["xray_installed"] else "[red]нет[/red]",
    )
    table.add_row(
        "Служба",
        f"[{status_color}]{result['service_active']}[/{status_color}]",
    )
    table.add_row("Версия Xray", result["version"])
    table.add_row("Uptime", result["uptime"])
    table.add_row(
        "Клиентов в конфиге",
        str(result["clients_count"]),
    )
    table.add_row(
        "Конфиг",
        "[green]OK[/green]" if result["config_ok"] else "[red]ошибка[/red]",
    )
    if result.get("error"):
        table.add_row("[red]Ошибка[/red]", f"[red]{result['error']}[/red]")

    console.print(table)

@app.command("edit")
def edit_cmd(
    server_id: int = typer.Option(..., "--id", help="ID сервера"),
    port: int = typer.Option(None, "--port", help="Новый порт Xray"),
    dest: str = typer.Option(None, "--dest", help="Новый dest (например, www.yahoo.com:443)"),
    sni: str = typer.Option(
        None, "--sni",
        help="Новый SNI (serverNames), через запятую если несколько",
    ),
):
    """Изменить параметры сервера (порт, dest, SNI)."""
    init_db()

    if port is None and dest is None and sni is None:
        console.print(
            "[yellow]Ничего не указано. Используй хотя бы один из: "
            "--port / --dest / --sni[/yellow]"
        )
        raise typer.Exit(code=1)

    new_sni = None
    if sni is not None:
        new_sni = [s.strip() for s in sni.split(",") if s.strip()]

    try:
        with console.status(f"[cyan]Изменяю настройки сервера id={server_id}...[/cyan]"):
            result = edit_server(
                server_id=server_id,
                new_port=port,
                new_dest=dest,
                new_server_names=new_sni,
            )
    except (SSHError, ImportError_) as e:
        console.print(Panel(f"[red]{e}", title="Ошибка"))
        raise typer.Exit(code=1)

    table = Table(title=f"Сервер {result['name']} обновлён", show_lines=True)
    table.add_column("Параметр", style="cyan")
    table.add_column("Было")
    table.add_column("Стало")

    if result["old_port"] != result["new_port"]:
        table.add_row("Порт", str(result["old_port"]), f"[green]{result['new_port']}[/green]")
    if result["old_dest"] != result["new_dest"]:
        table.add_row("dest", result["old_dest"], f"[green]{result['new_dest']}[/green]")
    if result["old_sni"] != result["new_sni"]:
        table.add_row(
            "SNI",
            ", ".join(result["old_sni"]),
            f"[green]{', '.join(result['new_sni'])}[/green]",
        )

    console.print(table)
    console.print("[dim]Xray перезапущен. Подписки обновятся автоматически.[/dim]")