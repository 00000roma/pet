# cli/menu.py
from __future__ import annotations

import json
import sys

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from db.database import init_db, get_session
from db.models import Server, User, UserServer

from core.server_manager import (
    import_existing_server,
    deploy_fresh,
    get_server_status,
    edit_server,
    ImportError_,
)
from core.ssh_client import SSHError
from core.user_manager import (
    add_user,
    remove_user,
    list_users,
    UserManagerError,
)
from core.subscription import (
    get_user_links,
    get_subscription_base64,
    SubscriptionError,
)

from services.server_runner import (
    start_server,
    stop_server,
    is_server_running,
    get_server_pid,
    get_server_url,
    get_log_path,
)

console = Console()

CUSTOM_STYLE = Style([
    ("qmark", "fg:#00afff bold"),
    ("question", "bold"),
    ("answer", "fg:#00afff bold"),
    ("pointer", "fg:#00afff bold"),
    ("highlighted", "fg:#00afff bold"),
    ("selected", "fg:#00afff"),
    ("separator", "fg:#6c6c6c"),
    ("instruction", "fg:#6c6c6c"),
])


# ---------- Вспомогательные функции ----------

def _header() -> None:
    console.clear()
    console.print(Panel.fit(
        "[bold cyan]Xray Manager[/bold cyan] [dim]v0.2[/dim]",
        border_style="cyan",
    ))


def _pause() -> None:
    questionary.press_any_key_to_continue(
        "Нажми любую клавишу для возврата в меню...",
        style=CUSTOM_STYLE,
    ).ask()


def _error(msg: str) -> None:
    console.print(Panel(f"[red]{msg}[/red]", title="Ошибка", border_style="red"))


def _success(msg: str) -> None:
    console.print(Panel(f"[green]{msg}[/green]", title="Готово", border_style="green"))


# ---------- Утилиты для серверов/юзеров ----------

def _get_all_servers() -> list[Server]:
    session = get_session()
    try:
        return session.query(Server).order_by(Server.id).all()
    finally:
        session.close()


def _server_choices(include_all: bool = False):
    servers = _get_all_servers()
    if not servers:
        return []
    choices = [
        questionary.Choice(
            title=f"{s.id}. {s.name} ({s.host}:{s.xray_port})",
            value=s.id,
        )
        for s in servers
    ]
    if include_all:
        choices.insert(0, questionary.Choice(
            title="Все серверы", value="all",
        ))
    return choices


# ---------- Главное меню ----------

def main_menu() -> None:
    while True:
        _header()
        choice = questionary.select(
            "Что делаем?",
            choices=[
                "Серверы",
                "Пользователи",
                "Подписки",
                "HTTP-сервер",
                "Выход",
            ],
            style=CUSTOM_STYLE,
        ).ask()

        if choice is None or choice == "Выход":
            console.print("[dim]Пока![/dim]")
            return
        elif choice == "Серверы":
            servers_menu()
        elif choice == "Пользователи":
            users_menu()
        elif choice == "Подписки":
            subscriptions_menu()
        elif choice == "HTTP-сервер":
            http_server_menu()


# ---------- Меню: Серверы ----------

def servers_menu() -> None:
    while True:
        _header()
        console.rule("[bold]Серверы[/bold]")
        choice = questionary.select(
            "Что делать?",
            choices=[
                "Список серверов",
                "Добавить новый сервер",
                "Импортировать существующий",
                "Проверить статус сервера",
                "Редактировать сервер",
                "Удалить сервер из БД",
                "Назад",
            ],
            style=CUSTOM_STYLE,
        ).ask()

        if choice is None or choice == "Назад":
            return
        elif choice == "Список серверов":
            _servers_list()
            _pause()
        elif choice == "Добавить новый сервер":
            _servers_add()
            _pause()
        elif choice == "Импортировать существующий":
            _servers_import()
            _pause()
        elif choice == "Проверить статус сервера":   # ← НОВАЯ ОБРАБОТКА
            _servers_status()
            _pause()
        elif choice == "Редактировать сервер":       # ← НОВАЯ ОБРАБОТКА
            _servers_edit()
            _pause()
        elif choice == "Удалить сервер из БД":
            _servers_remove()
            _pause()


def _servers_list() -> None:
    servers = _get_all_servers()
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

    for s in servers:
        table.add_row(
            str(s.id), s.name, s.host, str(s.xray_port),
            s.reality_dest,
            ", ".join(json.loads(s.reality_server_names or "[]")),
        )
    console.print(table)

def _servers_status() -> None:
    choices = _server_choices()
    if not choices:
        console.print("[yellow]Серверов нет.[/yellow]")
        return
    sid = questionary.select(
        "Какой сервер проверить?",
        choices=choices,
        style=CUSTOM_STYLE,
        instruction="(↑↓ — навигация, Enter — выбрать)",
    ).ask()
    if sid is None:
        return

    try:
        with console.status(f"[cyan]Проверяю сервер id={sid}...[/cyan]"):
            result = get_server_status(sid)
    except Exception as e:
        _error(str(e))
        return

    if not result.get("xray_installed"):
        _error(result.get("error") or "Xray не установлен.")
        return

    table = Table(title=f"Статус: {result['name']}", show_lines=True)
    table.add_column("Параметр", style="cyan")
    table.add_column("Значение")

    status_color = "green" if result["service_active"] == "active" else "red"
    table.add_row("Host", f"{result['host']}:{result['port']}")
    table.add_row(
        "Служба",
        f"[{status_color}]{result['service_active']}[/{status_color}]",
    )
    table.add_row("Версия Xray", result["version"])
    table.add_row("Uptime", result["uptime"])
    table.add_row("Клиентов в конфиге", str(result["clients_count"]))
    table.add_row(
        "Конфиг",
        "[green]OK[/green]" if result["config_ok"] else "[red]ошибка[/red]",
    )
    if result.get("error"):
        table.add_row("[red]Ошибка[/red]", f"[red]{result['error']}[/red]")

    console.print(table)

def _servers_edit() -> None:
    choices = _server_choices()
    if not choices:
        console.print("[yellow]Серверов нет.[/yellow]")
        return
    sid = questionary.select(
        "Какой сервер редактировать?",
        choices=choices,
        style=CUSTOM_STYLE,
    ).ask()
    if sid is None:
        return

    # Загрузим текущие параметры
    session = get_session()
    try:
        server = session.query(Server).filter_by(id=sid).one_or_none()
        if not server:
            _error(f"Сервер ID={sid} не найден.")
            return
        current_port = server.xray_port
        current_dest = server.reality_dest
        current_sni = ", ".join(json.loads(server.reality_server_names or "[]"))
    finally:
        session.close()

    console.rule(f"[bold]Редактирование: {server.name}[/bold]")
    console.print(f"[dim]Текущий порт: {current_port}[/dim]")
    console.print(f"[dim]Текущий dest: {current_dest}[/dim]")
    console.print(f"[dim]Текущий SNI:  {current_sni}[/dim]\n")

    # Спрашиваем, что менять
    field = questionary.select(
        "Что редактировать?",
        choices=[
            "Порт",
            "dest (маскировочный сайт)",
            "SNI (serverNames)",
            "Отмена",
        ],
        style=CUSTOM_STYLE,
    ).ask()

    if field is None or field == "Отмена":
        return

    new_port = None
    new_dest = None
    new_sni = None

    if field == "Порт":
        new_port_str = questionary.text(
            "Новый порт:",
            default=str(current_port),
            style=CUSTOM_STYLE,
        ).ask()
        try:
            new_port = int(new_port_str)
        except (ValueError, TypeError):
            _error("Порт должен быть числом.")
            return
    elif field == "dest (маскировочный сайт)":
        new_dest = questionary.text(
            "Новый dest (например, www.yahoo.com:443):",
            default=current_dest,
            style=CUSTOM_STYLE,
        ).ask()
        if not new_dest:
            return
    elif field == "SNI (serverNames)":
        new_sni_str = questionary.text(
            "Новый SNI (через запятую, если несколько):",
            default=current_sni,
            style=CUSTOM_STYLE,
        ).ask()
        if not new_sni_str:
            return
        new_sni = [s.strip() for s in new_sni_str.split(",") if s.strip()]

    # Подтверждение
    confirm = questionary.confirm(
        "Применить изменения? Xray будет перезапущен.",
        default=False,
        style=CUSTOM_STYLE,
    ).ask()
    if not confirm:
        return

    try:
        with console.status("[cyan]Обновляю сервер...[/cyan]"):
            result = edit_server(
                server_id=sid,
                new_port=new_port,
                new_dest=new_dest,
                new_server_names=new_sni,
            )
    except (SSHError, ImportError_, Exception) as e:
        _error(str(e))
        return

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

def _servers_add() -> None:
    console.rule("[bold]Добавление нового сервера[/bold]")
    console.print("[dim]Сервер должен быть чистым (без Xray).[/dim]\n")

    host = questionary.text("IP или домен сервера:", style=CUSTOM_STYLE).ask()
    if not host:
        return

    ssh_user = questionary.text(
        "SSH-пользователь:", default="root", style=CUSTOM_STYLE,
    ).ask()
    ssh_port = questionary.text(
        "SSH-порт:", default="22", style=CUSTOM_STYLE,
    ).ask()
    try:
        ssh_port = int(ssh_port)
    except ValueError:
        _error("Порт должен быть числом.")
        return

    key = questionary.text(
        "Путь к SSH-ключу:",
        default=f"{str(__import__('pathlib').Path.home())}/.ssh/id_ed25519",
        style=CUSTOM_STYLE,
    ).ask()
    if not key:
        return

    name = questionary.text(
        "Имя сервера:", default=host, style=CUSTOM_STYLE,
    ).ask()

    xray_port = questionary.text(
        "Порт Xray:", default="443", style=CUSTOM_STYLE,
    ).ask()
    try:
        xray_port = int(xray_port)
    except ValueError:
        _error("Порт должен быть числом.")
        return

    dest = questionary.text(
        "Сайт-маскировка (dest):",
        default="www.microsoft.com:443",
        style=CUSTOM_STYLE,
    ).ask()

    confirm = questionary.confirm(
        f"Развернуть Xray на {host}?",
        default=False, style=CUSTOM_STYLE,
    ).ask()
    if not confirm:
        return

    try:
        with console.status("[cyan]Разворачиваю Xray (1-3 минуты)...[/cyan]"):
            summary = deploy_fresh(
                host=host,
                ssh_key_path=key,
                ssh_port=ssh_port,
                ssh_user=ssh_user,
                name=name,
                xray_port=xray_port,
                dest=dest,
            )
    except (SSHError, ImportError_, Exception) as e:
        _error(str(e))
        return

    _success(
        f"Сервер развёрнут!\n"
        f"ID: {summary['server_id']}\n"
        f"Public key: {summary['public_key'][:30]}...\n"
        f"Short ID: {summary['short_id']}"
    )


def _servers_import() -> None:
    console.rule("[bold]Импорт существующего сервера[/bold]")

    host = questionary.text("IP или домен:", style=CUSTOM_STYLE).ask()
    if not host:
        return

    ssh_user = questionary.text(
        "SSH-пользователь:", default="root", style=CUSTOM_STYLE,
    ).ask()
    ssh_port = questionary.text(
        "SSH-порт:", default="22", style=CUSTOM_STYLE,
    ).ask()
    try:
        ssh_port = int(ssh_port)
    except ValueError:
        _error("Порт должен быть числом.")
        return

    key = questionary.text(
        "Путь к SSH-ключу:",
        default=f"{str(__import__('pathlib').Path.home())}/.ssh/id_ed25519",
        style=CUSTOM_STYLE,
    ).ask()

    name = questionary.text(
        "Имя сервера:", default=host, style=CUSTOM_STYLE,
    ).ask()

    try:
        with console.status(f"[cyan]Импортирую {host}...[/cyan]"):
            summary = import_existing_server(
                host=host, ssh_key_path=key,
                ssh_port=ssh_port, ssh_user=ssh_user, name=name,
            )
    except (SSHError, ImportError_, Exception) as e:
        _error(str(e))
        return

    _success(
        f"Сервер импортирован!\n"
        f"ID: {summary['server_id']}\n"
        f"Порт: {summary['port']}\n"
        f"Юзеров импортировано: {summary['users_imported']}"
    )


def _servers_remove() -> None:
    choices = _server_choices()
    if not choices:
        console.print("[yellow]Серверов нет.[/yellow]")
        return
    sid = questionary.select("Какой сервер удалить?", choices=choices,
                             style=CUSTOM_STYLE).ask()
    if sid is None:
        return

    # Посчитаем, сколько юзеров на сервере
    session = get_session()
    try:
        linked_users = (
            session.query(UserServer)
            .filter_by(server_id=sid)
            .count()
        )
        server = session.query(Server).filter_by(id=sid).one_or_none()
    finally:
        session.close()

    if not server:
        _error(f"Сервер ID={sid} не найден.")
        return

    msg = (
        f"Удалить сервер '{server.name}' (ID={sid}) из БД?\n"
        f"На нём {linked_users} связанных пользователей.\n"
        f"Связи будут тоже удалены.\n"
        f"Сам Xray на сервере останется работать."
    )
    confirm = questionary.confirm(msg, default=False, style=CUSTOM_STYLE).ask()
    if not confirm:
        return

    session = get_session()
    try:
        # Явно удаляем связи (даже с CASCADE — надёжнее)
        session.query(UserServer).filter_by(server_id=sid).delete()
        # Потом сам сервер
        session.delete(server)
        session.commit()
        _success(
            f"Сервер {server.name} удалён из БД.\n"
            f"Также удалено {linked_users} связей с пользователями."
        )
    finally:
        session.close()


# ---------- Меню: Пользователи ----------

def users_menu() -> None:
    while True:
        _header()
        console.rule("[bold]Пользователи[/bold]")
        choice = questionary.select(
            "Что делать?",
            choices=[
                "Список пользователей",
                "Добавить пользователя",
                "Удалить пользователя",
                "Показать ссылки пользователя",
                "Назад",
            ],
            style=CUSTOM_STYLE,
        ).ask()

        if choice is None or choice == "Назад":
            return
        elif choice == "Список пользователей":
            _users_list()
            _pause()
        elif choice == "Добавить пользователя":
            _users_add()
            _pause()
        elif choice == "Удалить пользователя":
            _users_remove()
            _pause()
        elif choice == "Показать ссылки пользователя":
            _users_show_links()
            _pause()


def _users_list() -> None:
    users = list_users()
    if not users:
        console.print("[yellow]Пользователей нет.[/yellow]")
        return

    table = Table(title="Пользователи", show_lines=True)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Email")
    table.add_column("UUID")
    table.add_column("Серверы")

    for u in users:
        servers_str = ", ".join(
            f"{s['name']}" for s in u["servers"]
        ) or "[dim]нет[/dim]"
        table.add_row(str(u["id"]), u["email"], u["uuid"][:16] + "...", servers_str)
    console.print(table)


def _users_add() -> None:
    console.rule("[bold]Добавление пользователя[/bold]")

    email = questionary.text("Email:", style=CUSTOM_STYLE).ask()
    if not email:
        return

    choices = _server_choices(include_all=True)
    if not choices:
        console.print("[yellow]Сначала добавь хотя бы один сервер.[/yellow]")
        return

    selected = questionary.checkbox(
        "На какие серверы добавить?",
        choices=[c for c in choices if c.value != "all"],
        style=CUSTOM_STYLE,
        instruction=(
            "(↑↓ — навигация, Пробел — выбрать, "
            "A — выбрать всё, I — инвертировать)"
        ),
    ).ask()
    if not selected:
        console.print("[yellow]Ничего не выбрано.[/yellow]")
        return

    with console.status("[cyan]Добавляю пользователя...[/cyan]"):
        try:
            uuid_str, results = add_user(email=email, server_ids=selected)
        except UserManagerError as e:
            _error(str(e))
            return

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


def _users_remove() -> None:
    users = list_users()
    if not users:
        console.print("[yellow]Пользователей нет.[/yellow]")
        return

    choices = [
        questionary.Choice(
            title=f"{u['email']} (серверов: {len(u['servers'])})",
            value=u["email"],
        )
        for u in users
    ]
    email = questionary.select("Кого удалить?", choices=choices,
                               style=CUSTOM_STYLE).ask()
    if not email:
        return

    confirm = questionary.confirm(
        f"Удалить {email} со всех серверов?", default=False,
        style=CUSTOM_STYLE,
    ).ask()
    if not confirm:
        return

    try:
        results = remove_user(email)
    except UserManagerError as e:
        _error(str(e))
        return

    table = Table(title=f"Удаление {email}", show_lines=True)
    table.add_column("Сервер", style="cyan")
    table.add_column("Host")
    table.add_column("Статус")
    table.add_column("Сообщение")

    for r in results:
        color = "green" if r.status == "ok" else "red"
        table.add_row(r.server_name, r.host, f"[{color}]{r.status}[/{color}]", r.message)

    console.print(table)


def _users_show_links() -> None:
    users = list_users()
    if not users:
        console.print("[yellow]Пользователей нет.[/yellow]")
        return

    choices = [
        questionary.Choice(title=u["email"], value=u["email"])
        for u in users
    ]
    email = questionary.select("Для кого?", choices=choices,
                               style=CUSTOM_STYLE).ask()
    if not email:
        return

    try:
        links = get_user_links(email)
    except SubscriptionError as e:
        _error(str(e))
        return

    for item in links:
        console.print(Panel(item.link, title=f"[cyan]{item.server_name}[/cyan]",
                            border_style="cyan"))


# ---------- Меню: Подписки ----------

def subscriptions_menu() -> None:
    while True:
        _header()
        console.rule("[bold]Подписки[/bold]")
        choice = questionary.select(
            "Что делать?",
            choices=[
                "Показать Base64-подписку",
                "Показать сырые vless:// ссылки",
                "Показать URL подписки",
                "Показать URL всех форматов",           # ← НОВЫЙ
                "Показать Happ routing (deep link)",    # ← НОВЫЙ
                "Назад",
            ],
            style=CUSTOM_STYLE,
        ).ask()

        if choice is None or choice == "Назад":
            return
        elif choice == "Показать Base64-подписку":
            _sub_show_base64()
            _pause()
        elif choice == "Показать сырые vless:// ссылки":
            _sub_show_raw()
            _pause()
        elif choice == "Показать URL подписки":
            _sub_show_url()
            _pause()
        elif choice == "Показать URL всех форматов":
            _sub_show_all_urls()
            _pause()
        elif choice == "Показать Happ routing (deep link)":
            _sub_show_happ_routing()
            _pause()


def _pick_user() -> str | None:
    users = list_users()
    if not users:
        console.print("[yellow]Пользователей нет.[/yellow]")
        return None
    choices = [
        questionary.Choice(title=u["email"], value=u["email"])
        for u in users
    ]
    return questionary.select("Для кого?", choices=choices,
                              style=CUSTOM_STYLE).ask()


def _sub_show_base64() -> None:
    email = _pick_user()
    if not email:
        return
    try:
        b64 = get_subscription_base64(email)
    except SubscriptionError as e:
        _error(str(e))
        return
    console.print(f"\n[bold]{email}[/bold] — Base64:\n")
    console.print(b64)

def _sub_show_all_urls() -> None:
    """Показать все доступные URL подписок для пользователя."""
    email = _pick_user()
    if not email:
        return

    # Определяем хост — берём из .env или вычисляем
    import os
    host = os.getenv("PUBLIC_HOST", "localhost")
    port = 8080
    base = f"http://{host}:{port}"

    console.print(Panel.fit(
        f"[bold]Base64-подписка (универсально):[/bold]\n"
        f"  {base}/sub/{email}\n\n"
        f"[bold]Сырой список vless://:[/bold]\n"
        f"  {base}/sub/{email}/raw\n\n"
        f"[bold]Xray JSON с правилами (Nekoray/v2rayN):[/bold]\n"
        f"  {base}/sub/{email}/xray.json\n\n"
        f"[bold]Happ routing — страница с кнопкой:[/bold]\n"
        f"  {base}/sub/{email}/happ-routing\n\n"
        f"[bold]Happ routing — сырой deep link:[/bold]\n"
        f"  {base}/sub/{email}/happ-routing/raw\n\n"
        f"[bold]Информация:[/bold]\n"
        f"  {base}/sub/{email}/info",
        title=f"URL подписок для {email}",
        border_style="cyan",
    ))


def _sub_show_happ_routing() -> None:
    """Сгенерировать и показать Happ routing deep link."""
    from core.happ_routing import build_happ_deep_link, ROUTING_PRESETS

    email = _pick_user()
    if not email:
        return

    preset = questionary.select(
        "Какой пресет использовать?",
        choices=[
            questionary.Choice(
                "Россия (реклама → block, РФ → direct)",
                value="ru",
            ),
            questionary.Choice(
                "Только AdBlock",
                value="adblock",
            ),
            questionary.Choice(
                "Глобально (всё через прокси)",
                value="global",
            ),
        ],
        style=CUSTOM_STYLE,
    ).ask()
    if not preset:
        return

    deep_link = build_happ_deep_link(
        preset=preset,
        custom_name=f"Reactive | {email}",
    )

    console.print(Panel.fit(
        f"[bold]Deep link для {email}[/bold]\n"
        f"Пресет: {preset}\n\n"
        f"[dim]1. Скопируй ссылку ниже[/dim]\n"
        f"[dim]2. Открой Happ → Routing → Импорт из буфера[/dim]\n"
        f"[dim]3. Сохрани[/dim]",
        title="Happ Routing",
        border_style="cyan",
    ))
    console.print(deep_link)





def _sub_show_raw() -> None:
    email = _pick_user()
    if not email:
        return
    try:
        links = get_user_links(email)
    except SubscriptionError as e:
        _error(str(e))
        return
    for item in links:
        console.print(Panel(item.link, title=item.server_name, border_style="cyan"))


def _sub_show_url() -> None:
    email = _pick_user()
    if not email:
        return
    if not is_server_running():
        console.print("[yellow]HTTP-сервер не запущен.[/yellow]")
        return
    url = get_server_url(port=8080)
    console.print(f"\n[bold]URL подписки:[/bold] {url}/sub/{email}")
    console.print("[dim]Вставь этот URL в клиент (Happ, v2rayNG, Nekoray).[/dim]")


# ---------- Меню: HTTP-сервер ----------

def http_server_menu() -> None:
    while True:
        _header()
        console.rule("[bold]HTTP-сервер подписок[/bold]")

        if is_server_running():
            pid = get_server_pid()
            console.print(f"Статус: [green]запущен[/green] (PID {pid})")
            console.print(f"URL:    {get_server_url(port=8080)}")
        else:
            console.print("Статус: [red]остановлен[/red]")

        console.print(f"Логи:   {get_log_path()}\n")

        choices = [
            "Запустить" if not is_server_running() else "Перезапустить",
            "Остановить" if is_server_running() else None,
            "Показать логи",
            "Открыть в браузере",
            "Назад",
        ]
        choices = [c for c in choices if c]

        choice = questionary.select("Действие:", choices=choices,
                                    style=CUSTOM_STYLE).ask()
        if choice is None or choice == "Назад":
            return
        elif choice in ("Запустить", "Перезапустить"):
            if is_server_running():
                stop_server()
            try:
                pid = start_server(port=8080)
                _success(f"HTTP-сервер запущен (PID {pid}).")
            except Exception as e:
                _error(f"Не удалось запустить: {e}")
            _pause()
        elif choice == "Остановить":
            stop_server()
            _success("HTTP-сервер остановлен.")
            _pause()
        elif choice == "Показать логи":
            log_file = get_log_path()
            if log_file.exists():
                lines = log_file.read_text(encoding="utf-8").splitlines()[-30:]
                console.print("\n".join(lines))
            else:
                console.print("[yellow]Логов ещё нет.[/yellow]")
            _pause()
        elif choice == "Открыть в браузере":
            import webbrowser
            webbrowser.open(get_server_url(port=8080))
            _pause()


# ---------- Точка входа меню ----------

def run_menu() -> None:
    init_db()
    # Автозапуск HTTP-сервера в фоне
    if not is_server_running():
        try:
            pid = start_server(port=8080, wait_ready=True)
            console.print(f"[dim]HTTP-сервер запущен в фоне (PID {pid}).[/dim]")
        except Exception as e:
            console.print(f"[yellow]Не удалось запустить HTTP-сервер: {e}[/yellow]")

    main_menu()