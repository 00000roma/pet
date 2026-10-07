# cli/serve_commands.py
from __future__ import annotations

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel

from db.database import init_db

app = typer.Typer(help="HTTP-сервер подписок")
console = Console()


@app.command("run")
def run_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Адрес для прослушивания"),
    port: int = typer.Option(8080, "--port", "-p", help="Порт"),
    reload: bool = typer.Option(
        False, "--reload", help="Авто-перезагрузка при изменениях (для разработки)"
    ),
):
    """Запустить HTTP-сервер подписок."""
    init_db()  # убедимся, что таблицы есть

    console.print(Panel.fit(
        f"[green]Запускаю HTTP-сервер подписок[/green]\n"
        f"Адрес: [bold]http://{host}:{port}[/bold]\n"
        f"Swagger: [bold]http://{host}:{port}/docs[/bold]\n"
        f"Подписка: [bold]http://{host}:{port}/sub/<email>[/bold]\n\n"
        f"[dim]Ctrl+C — остановить[/dim]",
        title="serve",
    ))

    try:
        uvicorn.run(
            "services.api.app:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Сервер остановлен.[/yellow]")