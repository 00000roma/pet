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
from core.monitoring import get_server_metrics, SPEED_DEFAULT_MB
from core.ssh_client import SSHError
from db.database import init_db, get_session
from db.models import Server
from cli.monitoring_view import render_metrics

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
        table.add_column("Транспорт")
        table.add_column("dest")
        table.add_column("SNI")
        table.add_column("Статус")

        for s in servers:
            table.add_row(
                str(s.id),
                s.name,
                s.host,
                str(s.xray_port),
                s.network or "xhttp",
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


@app.command("monitor")
def monitor_cmd(
    server_id: int = typer.Option(..., "--id", help="ID сервера"),
    speed_mb: int = typer.Option(SPEED_DEFAULT_MB, "--speed-mb", help="Объём теста скорости (МБ)"),
    no_speed: bool = typer.Option(False, "--no-speed", help="Пропустить тест скорости"),
):
    """Мониторинг сервера: нагрузка, канал связи, подключения."""
    init_db()
    try:
        with console.status(f"[cyan]Собираю метрики сервера id={server_id}...[/cyan]"):
            metrics = get_server_metrics(server_id, speed_mb=0 if no_speed else speed_mb)
    except Exception as e:
        console.print(Panel(f"[red]{e}", title="Ошибка мониторинга"))
        raise typer.Exit(code=1)

    render_metrics(metrics, console)


@app.command("edit")
def edit_cmd(
    server_id: int = typer.Option(..., "--id", help="ID сервера"),
    port: int = typer.Option(None, "--port", help="Новый порт Xray"),
    dest: str = typer.Option(None, "--dest", help="Новый dest (например, www.yahoo.com:443)"),
    sni: str = typer.Option(
        None, "--sni",
        help="Новый SNI (serverNames), через запятую если несколько",
    ),
    network: str = typer.Option(
        None, "--network", help="Транспорт: xhttp или grpc",
    ),
    grpc_service_name: str = typer.Option(
        None, "--grpc-service-name",
        help="serviceName для gRPC (используется при --network grpc)",
    ),
    xhttp_path: str = typer.Option(
        None, "--xhttp-path",
        help="path для XHTTP (используется при --network xhttp)",
    ),
    xhttp_mode: str = typer.Option(
        None, "--xhttp-mode",
        help="mode для XHTTP: auto, packet-up, stream-one, stream-up",
    ),
    xhttp_host: str = typer.Option(
        None, "--xhttp-host",
        help="Host header для XHTTP (пустая строка — убрать host)",
    ),
    fingerprint: str = typer.Option(
        None, "--fingerprint",
        help="TLS-отпечаток клиента: chrome, safari, firefox, edge, ios, android, random",
    ),
):
    """Изменить параметры сервера (порт, dest, SNI, транспорт, fingerprint)."""
    init_db()

    if all(
        v is None
        for v in (
            port, dest, sni, network, grpc_service_name,
            xhttp_path, xhttp_mode, xhttp_host, fingerprint,
        )
    ):
        console.print(
            "[yellow]Ничего не указано. Используй хотя бы один из: "
            "--port / --dest / --sni / --network / --fingerprint / "
            "--xhttp-path / --xhttp-mode / --xhttp-host[/yellow]"
        )
        raise typer.Exit(code=1)

    if network is not None and network not in ("xhttp", "grpc"):
        console.print("[red]--network должен быть 'xhttp' или 'grpc'.[/red]")
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
                new_network=network,
                grpc_service_name=grpc_service_name,
                xhttp_path=xhttp_path,
                xhttp_mode=xhttp_mode,
                xhttp_host=xhttp_host,
                fingerprint=fingerprint,
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

    if result.get("old_network") != result.get("new_network"):
        table.add_row(
            "Транспорт",
            result["old_network"],
            f"[green]{result['new_network']}[/green]",
        )

    if result.get("old_fingerprint") != result.get("new_fingerprint"):
        table.add_row(
            "fingerprint",
            result["old_fingerprint"],
            f"[green]{result['new_fingerprint']}[/green]",
        )

    if result.get("old_xhttp_path") != result.get("new_xhttp_path"):
        table.add_row(
            "XHTTP path",
            result["old_xhttp_path"],
            f"[green]{result['new_xhttp_path']}[/green]",
        )

    if result.get("old_xhttp_mode") != result.get("new_xhttp_mode"):
        table.add_row(
            "XHTTP mode",
            result["old_xhttp_mode"],
            f"[green]{result['new_xhttp_mode']}[/green]",
        )

    if result.get("old_xhttp_host") != result.get("new_xhttp_host"):
        table.add_row(
            "XHTTP host",
            result["old_xhttp_host"] or "(пусто)",
            f"[green]{result['new_xhttp_host'] or '(пусто)'}[/green]",
        )

    console.print(table)
    console.print("[dim]Xray перезапущен. Подписки обновятся автоматически.[/dim]")