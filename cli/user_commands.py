from __future__ import annotations

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
    _get_server,           # ← НОВОЕ
    _sync_users_batch,     # ← НОВОЕ (мы его используем в add-bulk)
)
from db.database import init_db, get_session
from db.models import User, Server, UserServer
from core.links import get_public_url

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
            public_url = get_public_url()
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

    public_url = get_public_url()

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
        True, "--skip-existing/--no-skip-existing",
        help="Пропускать существующих пользователей (по умолчанию — да)",
    ),
):
    """Создать пользователей из файла (один email на строку). Батчевая обработка."""
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

    # 3. Собираем список новых пользователей (создаём User в БД, но не синхронизируем)
    import uuid as _uuid
    session = get_session()
    try:
        existing_emails = {u.email for u in session.query(User).all()}
    finally:
        session.close()

    new_users: list[dict] = []
    existing_users: list[str] = []

    session = get_session()
    try:
        for email in emails:
            if email in existing_emails:
                # Пользователь уже есть — используем существующий User
                user = session.query(User).filter_by(email=email).one()
                new_users.append({
                    "uuid": None,   # заполним ниже per-server
                    "email": user.email,
                    "user_id": user.id,
                    "is_new": False,
                })
                existing_users.append(email)
            else:
                # Создаём нового User с токеном
                user = User(
                    uuid=str(_uuid.uuid4()),
                    email=email,
                    token=__import__("secrets").token_urlsafe(24),
                )
                session.add(user)
                session.flush()
                new_users.append({
                    "uuid": user.uuid,
                    "email": user.email,
                    "user_id": user.id,
                    "is_new": True,
                })
                existing_emails.add(email)
        session.commit()
    finally:
        session.close()

    console.print(
        f"[green]Пользователей: {len(new_users)}[/green] "
        f"([dim]новых: {sum(1 for u in new_users if u['is_new'])}, "
        f"существующих: {sum(1 for u in new_users if not u['is_new'])}[/dim])"
    )

    # 4. Для каждого сервера — БАТЧ-синхронизация
    created_links: list[dict] = []
    failed: list[tuple[str, str]] = []

    for sid in server_ids:
        try:
            server = _get_server(sid)
        except UserManagerError as e:
            failed.append((f"server-{sid}", str(e)))
            continue

        # Готовим список users с UUID для этого сервера
        server_users: list[dict] = []
        for u in new_users:
            server_uuid = str(_uuid.uuid4())    # новый UUID для этого сервера
            server_users.append({
                "uuid": server_uuid,
                "email": u["email"],
                "flow": "",
            })
            created_links.append({
                "server_id": server.id,
                "server_name": server.name,
                "user_id": u["user_id"],
                "email": u["email"],
                "uuid": server_uuid,
            })

        # Синхронизируем ВСЕХ пользователей за один SSH + один рестарт Xray
        try:
            with console.status(
                f"[cyan]Добавляю {len(server_users)} пользователей на {server.name} "
                f"(один рестарт Xray)...[/cyan]"
            ):
                results = _sync_users_batch(server, server_users)

            # Считаем успехи/ошибки
            ok_count = sum(1 for r in results if r.status == "ok")
            err_count = sum(1 for r in results if r.status == "error")
            console.print(
                f"  [green]✓[/green] {server.name}: "
                f"[green]{ok_count}[/green] ok, "
                f"[red]{err_count}[/red] ошибок"
            )

            for r in results:
                if r.status == "error":
                    failed.append((server.name, r.message))
        except Exception as e:
            failed.append((server.name, str(e)))
            continue

    # 5. Сохраняем связи UserServer в БД (одним батчем)
    session = get_session()
    try:
        for link in created_links:
            exists = (
                session.query(UserServer)
                .filter_by(user_id=link["user_id"], server_id=link["server_id"])
                .one_or_none()
            )
            if exists:
                continue
            session.add(UserServer(
                user_id=link["user_id"],
                server_id=link["server_id"],
                uuid=link["uuid"],
                flow="",
            ))
        session.commit()
    finally:
        session.close()

    # 6. Итог
    console.print()
    console.print(Panel(
        f"[green]Пользователей создано:[/green] {sum(1 for u in new_users if u['is_new'])}\n"
        f"[yellow]Уже существовало:[/yellow] {sum(1 for u in new_users if not u['is_new'])}\n"
        f"[red]Ошибок:[/red] {len(failed)}",
        title="Готово",
        border_style="green" if not failed else "yellow",
    ))

    # 7. Таблица ссылок
    public_url = get_public_url()

    if new_users:
        table = Table(title="Ссылки для пользователей", show_lines=False)
        table.add_column("Email", style="cyan")
        table.add_column("Ссылка")

        # Получаем токены для всех
        session = get_session()
        try:
            for u in new_users:
                user = session.query(User).filter_by(id=u["user_id"]).one()
                link = f"{public_url}/go/{user.token}"
                table.add_row(u["email"], link)
        finally:
            session.close()

        console.print(table)

        # Сохраняем в файл
        output_path = path.with_suffix(".links.txt")
        session = get_session()
        try:
            with output_path.open("w", encoding="utf-8") as f:
                for u in new_users:
                    user = session.query(User).filter_by(id=u["user_id"]).one()
                    link = f"{public_url}/go/{user.token}"
                    f.write(f"{u['email']}\t{link}\n")
        finally:
            session.close()

        console.print(f"[dim]Ссылки сохранены в {output_path}[/dim]")

    # 8. Ошибки
    if failed:
        console.print()
        err_table = Table(title="Ошибки", show_lines=False)
        err_table.add_column("Источник", style="red")
        err_table.add_column("Причина")
        for src, reason in failed:
            err_table.add_row(src, reason)
        console.print(err_table)

@app.command("show")
def show_cmd(
    email: str = typer.Option(..., "--email", "-e", help="Email пользователя"),
):
    """Показать детали пользователя: серверы, UUID, ссылки."""
    init_db()

    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        if not user:
            console.print(Panel(f"[red]Пользователь '{email}' не найден.[/red]"))
            raise typer.Exit(code=1)

        public_url = get_public_url()

        # Основная инфо
        console.print(Panel(
            f"Email:    [bold]{user.email}[/bold]\n"
            f"UUID:     {user.uuid}\n"
            f"Token:    {user.token}\n"
            f"Создан:   {user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else '—'}\n\n"
            f"[bold]Ссылка:[/bold] {public_url}/go/{user.token}\n"
            f"[bold]JSON:[/bold]   {public_url}/sub/{user.token}/xray.json",
            title=f"Пользователь: {user.email}",
            border_style="cyan",
        ))

        # Серверы
        links = (
            session.query(UserServer, Server)
            .join(Server, UserServer.server_id == Server.id)
            .filter(UserServer.user_id == user.id)
            .order_by(Server.name)
            .all()
        )

        if not links:
            console.print("[yellow]Пользователь не привязан ни к одному серверу.[/yellow]")
            return

        table = Table(title="Серверы", show_lines=False)
        table.add_column("Сервер", style="cyan")
        table.add_column("Host")
        table.add_column("Порт")
        table.add_column("UUID")
        table.add_column("Flow")

        for link_row, server in links:
            table.add_row(
                server.name,
                server.host,
                str(server.xray_port),
                link_row.uuid[:16] + "...",
                link_row.flow or "—",
            )

        console.print(table)
    finally:
        session.close()

@app.command("export-links")
def export_links_cmd(
    output: str = typer.Option(
        "data/all_users.links.txt",
        "--output", "-o",
        help="Путь к выходному файлу",
    ),
):
    """Выгрузить все ссылки пользователей в файл (email<TAB>ссылка)."""
    init_db()

    session = get_session()
    try:
        users = session.query(User).order_by(User.email).all()
        if not users:
            console.print("[yellow]Пользователей нет.[/yellow]")
            return

        public_url = get_public_url()

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as f:
            for user in users:
                link = f"{public_url}/go/{user.token}"
                f.write(f"{user.email}\t{link}\n")

        console.print(Panel(
            f"[green]Готово[/green]\n\n"
            f"Пользователей: [bold]{len(users)}[/bold]\n"
            f"Файл:          [bold]{output_path}[/bold]",
            title="Экспорт ссылок",
            border_style="green",
        ))

        # Первые 5 строк для проверки
        console.print("\n[dim]Первые 5 строк:[/dim]")
        with output_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                console.print(f"  {line.rstrip()}")
    finally:
        session.close()