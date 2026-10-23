# cli/monitoring_view.py
"""Отрисовка результатов мониторинга (rich-таблицы)."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def _fmt(v) -> str:
    if v is None:
        return "[dim]—[/dim]"
    return str(v)


def _fmt_ms(v) -> str:
    if v is None:
        return "—"
    return f"{v:.1f} мс"


def _verdict(color: str) -> str:
    labels = {
        "red": "[red]плохо[/red]",
        "yellow": "[yellow]норм[/yellow]",
        "green": "[green]ок[/green]",
    }
    return labels.get(color, "")


def _load_color(load1, cores) -> str:
    if load1 is None or cores is None or cores <= 0:
        return ""
    ratio = load1 / cores
    if ratio >= 1.0:
        return "red"
    if ratio >= 0.7:
        return "yellow"
    return "green"


def _ms_color(v) -> str:
    if v is None:
        return ""
    if v >= 200:
        return "red"
    if v >= 100:
        return "yellow"
    return "green"


def _speed_color(v) -> str:
    if v is None:
        return ""
    if v < 10:
        return "red"
    if v < 50:
        return "yellow"
    return "green"


def _mem_color(used_mb, total_mb) -> str:
    if used_mb is None or total_mb is None or total_mb <= 0:
        return ""
    pct = used_mb / total_mb * 100
    if pct >= 90:
        return "red"
    if pct >= 75:
        return "yellow"
    return "green"


def _human_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {mins} мин"
    return f"{mins} мин"


def render_metrics(metrics: dict, console: Console) -> None:
    """Печатает результат get_server_metrics в виде таблиц."""
    if not metrics.get("host") and not metrics.get("name"):
        msg = "\n".join(metrics.get("errors") or ["Нет данных."])
        console.print(Panel(f"[red]{msg}[/red]", title="Ошибка мониторинга"))
        return

    # --- Шапка ---
    header = Table.grid(padding=(0, 2))
    header.add_column(justify="right", style="cyan")
    header.add_column()
    header.add_row("Сервер", metrics.get("name") or "?")
    header.add_row("Адрес", f"{metrics.get('host')}:{metrics.get('port')}")

    service = metrics.get("service_active", "unknown")
    sc = "green" if service == "active" else "red"
    header.add_row("Служба", f"[{sc}]{service}[/{sc}]")

    uptime = metrics.get("uptime")
    header.add_row("Uptime", _human_uptime(uptime) if uptime is not None else "—")
    console.print(Panel(header, title="Мониторинг", border_style="cyan"))

    # --- Нагрузка ---
    load = metrics.get("load") or {}
    cores = metrics.get("cpu_cores")
    mem = metrics.get("mem") or {}
    l1, l5, l15 = load.get("1"), load.get("5"), load.get("15")

    load_t = Table(title="Нагрузка", show_header=True, header_style="bold cyan")
    load_t.add_column("Параметр", style="cyan")
    load_t.add_column("Значение")
    load_t.add_column("Оценка")

    lc = _load_color(l1, cores)
    load_t.add_row(
        "Load average", f"{_fmt(l1)} / {_fmt(l5)} / {_fmt(l15)}", _verdict(lc)
    )
    load_t.add_row("Ядер CPU", _fmt(cores), "")
    if cores and l1 is not None and cores > 0:
        load_t.add_row("Load / ядро", f"{l1 / cores:.2f}", _verdict(lc))

    mem_total = mem.get("total_mb")
    mem_used = mem.get("used_mb")
    mc = _mem_color(mem_used, mem_total)
    mem_s = "—"
    if mem_used is not None and mem_total is not None:
        mem_s = f"{mem_used} / {mem_total} МБ ({mem_used / mem_total * 100:.0f}%)"
    load_t.add_row("Память", mem_s, _verdict(mc))
    console.print(load_t)

    # --- Канал связи ---
    lat_ssh = metrics.get("latency_ssh") or {}
    lat_net = metrics.get("latency_internet") or {}
    speed = metrics.get("speed") or {}
    net = metrics.get("net") or {}

    link_t = Table(title="Канал связи", show_header=True, header_style="bold cyan")
    link_t.add_column("Параметр", style="cyan")
    link_t.add_column("Значение")
    link_t.add_column("Оценка")

    ssh_avg = lat_ssh.get("avg")
    link_t.add_row(
        "Пинг до сервера (SSH)",
        f"{_fmt_ms(lat_ssh.get('min'))} / {_fmt_ms(ssh_avg)} / "
        f"{_fmt_ms(lat_ssh.get('max'))} (min/avg/max)",
        _verdict(_ms_color(ssh_avg)),
    )

    in_avg = lat_net.get("avg")
    loss = lat_net.get("loss_pct")
    loss_s = f", потери {loss:.0f}%" if loss is not None else ""
    link_t.add_row(
        "Пинг в интернет (с сервера)",
        f"{_fmt_ms(lat_net.get('min'))} / {_fmt_ms(in_avg)} / "
        f"{_fmt_ms(lat_net.get('max'))}{loss_s}",
        _verdict(_ms_color(in_avg)),
    )

    if speed.get("skipped"):
        link_t.add_row("Скорость интернета (тест)", "[dim]тест пропущен[/dim]", "")
    elif speed.get("error"):
        link_t.add_row("Скорость интернета (тест)", f"[red]{speed['error']}[/red]", "")
    else:
        down = speed.get("download_mbps")
        up = speed.get("upload_mbps")
        if down is None and up is None:
            link_t.add_row("Скорость интернета (тест)", "—", "")
        else:
            down_s = f"{down:.1f} Мбит/с" if down is not None else "—"
            up_s = f"{up:.1f} Мбит/с" if up is not None else "—"
            link_t.add_row(
                "Скорость интернета (тест)",
                f"↓ {down_s} / ↑ {up_s} ({speed.get('mb')} МБ)",
                _verdict(_speed_color(down if down is not None else up)),
            )

    iface = net.get("iface")
    if iface:
        rx = net.get("rx_mbps")
        tx = net.get("tx_mbps")
        rx_s = f"{rx:.1f} Мбит/с" if rx is not None else "—"
        tx_s = f"{tx:.1f} Мбит/с" if tx is not None else "—"
        link_t.add_row(f"Канал сейчас ({iface})", f"↓ {rx_s} / ↑ {tx_s}", "")
        link_t.add_row(
            f"Всего ({iface})",
            f"↓ {net.get('rx_total') or '—'} / ↑ {net.get('tx_total') or '—'}",
            "",
        )

    console.print(link_t)

    # --- Подключения ---
    conn = metrics.get("connections") or {}
    conn_t = Table(title="Подключения", show_header=True, header_style="bold cyan")
    conn_t.add_column("Параметр", style="cyan")
    conn_t.add_column("Значение")
    conn_t.add_row("Активных соединений", _fmt(conn.get("total")))
    conn_t.add_row("Уникальных IP (≈ пользователей)", _fmt(conn.get("unique_ips")))
    console.print(conn_t)

    if metrics.get("errors"):
        console.print(
            Panel("\n".join(metrics["errors"]), title="Замечания", border_style="yellow")
        )
