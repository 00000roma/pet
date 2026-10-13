from __future__ import annotations

import os
from pathlib import Path

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
from db.database import init_db, get_session
from db.models import User, Server

app = typer.Typer(help="Управление пользователями")
console = Console()


def _parse_server_ids(raw: str) -> list[int]:
    if raw.strip().lower() == "all":
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
        "", "--flow",
        help="Flow (по умолчанию пустой для XHTTP)",
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

    # Показать токен и ссылки
    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if user:
            public_url = os.getenv("PUBLIC_URL", "http://172.16.200.204:8080").rstrip("/")
            console.print()
            console.print(Panel(
                f"Email: [bold]{user.email}[/bold]\n"
                f"UUID:  {user.uuid}\n"
                f"Token: {user.token}\n\n"
                f"[bold]Ссылка для пользователя:[/bold]\n"
                f"  {public_url}/go/{user.token}\n\n"
                f"[bold]JSON-подписка:[/bold]\n"
                f"  {public_url}/sub/{user.token}/xray.json",
                title="Готово",
                border_style="green",
            ))
    finally:
        session.close()


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
def list_cmd(
    with_links: bool = typer.Option(
        False, "--with-links",
        help="Показать ссылки /go/{token}",
    ),
):
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

    if with_links:
        table.add_column("Ссылка")

    public_url = os.getenv("PUBLIC_URL", "http://172.16.200.204:8080").rstrip("/")

    session = get_session()
    try:
        for u in users:
            servers_str = ", ".join(
                f"{s['name']}({s['host']})" for s in u["servers"]
            ) or "[dim]нет[/dim]"

            row = [str(u["id"]), u["email"], u["uuid"][:16] + "...", servers_str]

            if with_links:
                user = session.query(User).filter_by(id=u["id"]).one_or_none()
                if user and user.token:
                    row.append(f"{public_url}/go/{user.token}")
                else:
                    row.append("[dim]—[/dim]")

            table.add_row(*row)
    finally:
        session.close()

    console.print(table)


@app.command("add-bulk")
def add_bulk_cmd(
    file: str = typer.Option(..., "--file", "-f", help="Путь к файлу со списком email"),
    servers: str = typer.Option("all", "--servers", "-s", help="ID серверов или 'all'"),
    skip_existing: bool = typer.Option(
        True, "--skip-existing",
        help="Пропускать существующих пользователей",
    ),
):
    """Создать пользователей из файла (один email на строку)."""
    init_db()

    # 1. Читаем файл
    path = Path(file)
    if not path.exists():
        console.print(Panel(f"[red]Файл не найден: {file}", title="Ошибка"))
        raise typer.Exit(code=1)

    emails: list[str] = []
    skipped_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            skipped_lines += 1
            continue
        if "@" not in line:
            skipped_lines += 1
            continue
        emails.append(line.lower())

    if not emails:
        console.print("[yellow]Не найдено ни одного email.[/yellow]")
        raise typer.Exit(code=0)

    console.print(Panel(
        f"Прочитано строк: [bold]{len(emails) + skipped_lines}[/bold]\n"
        f"Валидных email: [bold]{len(emails)}[/bold]\n"
        f"Пропущено: {skipped_lines}",
        title="Чтение файла",
        border_style="cyan",
    ))

    # 2. Парсим серверы
    try:
        server_ids = _parse_server_ids(servers)
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if not server_ids:
        console.print("[yellow]Нет серверов.[/yellow]")
        raise typer.Exit(code=1)

    # 3. Создаём пользователей
    created: list[dict] = []
    existing: list[str] = []
    failed: list[tuple[str, str]] = []

    with console.status(f"[cyan]Создаю {len(emails)} пользователей...[/cyan]"):
        for email in emails:
            try:
                uuid_str, results = add_user(email=email, server_ids=server_ids)

                failed_servers = [r for r in results if r.status == "error"]
                if failed_servers:
                    failed.append((
                        email,
                        "; ".join(f"{r.server_name}: {r.message}" for r in failed_servers),
                    ))
                    continue

                session = get_session()
                try:
                    user = session.query(User).filter_by(email=email).one()
                    token = user.token
                finally:
                    session.close()

                created.append({"email": email, "token": token})

            except UserManagerError as e:
                msg = str(e).lower()
                if "already exists" in msg or "уже" in msg:
                    if skip_existing:
                        existing.append(email)
                        continue
                failed.append((email, str(e)))
            except Exception as e:
                failed.append((email, str(e)))

    # 4. Итог
    console.print()
    console.print(Panel(
        f"[green]Создано:[/green] {len(created)}\n"
        f"[yellow]Уже существует:[/yellow] {len(existing)}\n"
        f"[red]Ошибок:[/red] {len(failed)}",
        title="Готово",
        border_style="green" if not failed else "yellow",
    ))

    # 5. Таблица ссылок
    if created:
        public_url = os.getenv("PUBLIC_URL", "http://172.16.200.204:8080").rstrip("/")
        table = Table(title="Ссылки для пользователей", show_lines=False)
        table.add_column("Email", style="cyan")
        table.add_column("Ссылка")

        for item in created:
            link = f"{public_url}/go/{item['token']}"
            table.add_row(item["email"], link)

        console.print(table)

        # Сохраняем в файл
        output_path = path.with_suffix(".links.txt")
        with output_path.open("w", encoding="utf-8") as f:
            for item in created:
                link = f"{public_url}/go/{item['token']}"
                f.write(f"{item['email']}\t{link}\n")

        console.print(f"[dim]Ссылки сохранены в {output_path}[/dim]")

    # 6. Ошибки
    if failed:
        console.print()
        err_table = Table(title="Ошибки", show_lines=False)
        err_table.add_column("Email", style="red")
        err_table.add_column("Причина")
        for email, reason in failed:
            err_table.add_row(email, reason)
        console.print(err_table)