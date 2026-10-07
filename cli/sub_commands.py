# cli/sub_commands.py
from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.panel import Panel

from core.subscription import (
    get_user_links,
    get_subscription_base64,
    SubscriptionError,
)

app = typer.Typer(help="Управление подписками")
console = Console()


def _print_raw(text: str) -> None:
    """
    Печатает строку БЕЗ форматирования Rich:
    - никаких рамок
    - никаких переносов по ширине терминала
    - длинная строка уйдёт за край экрана, но при копировании
      будет целой (терминал сам разберётся)
    """
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


@app.command("show")
def show_cmd(
    email: str = typer.Option(..., "--email", "-e", help="Email пользователя"),
    base64_output: bool = typer.Option(
        False, "--base64", "-b", help="Вывести подписку в Base64 (для URL-подписки)"
    ),
    raw: bool = typer.Option(
        False, "--raw", "-r",
        help="Вывести без оформления — для копирования в клиент",
    ),
):
    """Показать ссылки vless:// для пользователя."""
    try:
        # --- Base64 ---
        if base64_output:
            encoded = get_subscription_base64(email)
            if raw:
                _print_raw(encoded)
            else:
                console.print(Panel(encoded, title=f"Подписка (Base64) для {email}"))
            return

        # --- vless:// ссылки ---
        links = get_user_links(email)
        if not links:
            console.print(f"[yellow]У {email} нет доступных серверов.[/yellow]")
            return

        if raw:
            for item in links:
                _print_raw(item.link)
            return

        for item in links:
            console.print(
                Panel(
                    item.link,
                    title=f"[cyan]{item.server_name}[/cyan] ({item.server_host})",
                    subtitle=f"[dim]{email}[/dim]",
                )
            )
    except SubscriptionError as e:
        console.print(Panel(f"[red]{e}", title="Ошибка"))
        raise typer.Exit(code=1)