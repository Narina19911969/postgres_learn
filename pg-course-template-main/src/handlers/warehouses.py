from dataclasses import dataclass

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_WAREHOUSES
from auth import ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER

from prompt_toolkit.shortcuts import choice


def _get_cities_from_db() -> list:
    """Запрашиваем текстовые имена городов из таблицы catalog.cities"""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM catalog.cities ORDER BY name")
        # Для choice передаем кортеж: (значение, отображаемый_текст)
        # Так как нам нужен текст, имя города выступает и ключом, и значением
        return [(row[0], row[0]) for row in cur.fetchall()]



@dataclass
class Warehouse:
    id: int
    city: str
    address: str
    label: str | None
    is_central: bool


def _render_warehouse(warehouse: Warehouse) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))

    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")

    table.add_row("ID", str(warehouse.id))
    table.add_row("Город", warehouse.city)
    table.add_row("Адрес", warehouse.address)
    table.add_row("Метка", warehouse.label or "")
    table.add_row("Центральный", "Да" if warehouse.is_central else "Нет", style="bold green" if warehouse.is_central else "white")
    panel = Panel(
        table,
        expand=False,
        title=f"[bold green]Склад #{warehouse.id}[/bold green]",
        border_style="green",
    )

    console.print(panel)


@command("list warehouses", "список всех складов", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER],)
def list_warehouses() -> None:
    conn = get_conn()
    table = Table(title="Склады", show_header=True, header_style="bold cyan")

    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Город", style="green", min_width=20)
    table.add_column("Адрес", style="yellow", min_width=30)
    table.add_column("Метка", style="magenta", min_width=15)
    table.add_column("Центральный", style="magenta", min_width=15)


    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses")
        warehouses: list[Warehouse] = cur.fetchall()

    for warehouse in warehouses:
        if warehouse.is_central:
            type_text = "[bold red]Центральный[/bold red]"
        else:
            type_text = "[dim]Обычный[/dim]"

        table.add_row(
            str(warehouse.id),
            warehouse.city,
            warehouse.address,
            warehouse.label or "",
            type_text,
        )
    console.print(table)


@command("show warehouse", "информация о складе", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER, ROLE_SALES_MANAGER])
def show_warehouse(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (_id,))
        warehouse: Warehouse | None = cur.fetchone()

    if warehouse is None:
        render_error(f"Склад с ID {_id} не найден")
        return

    _render_warehouse(warehouse)


@command("add warehouse", "добавить склад (интерактивно)", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER],)
def add_warehouse() -> None:
    conn = get_conn()
    city_options = _get_cities_from_db()

    city = choice(message="Выберите город расположения склада:", options=city_options)
    if city is None: return

    address = prompt("Адрес: ", validator=NonEmptyValidator()).strip()
    label = prompt("Метка (необязательно): ").strip() or None

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.warehouses")
        count = cur.fetchone()[0]

    if count == 0:
        is_central = True
        console.print("[yellow]Это первый склад в системе. Он автоматически назначен центральным.[/yellow]")
    else:
        ans = prompt("Сделать этот склад центральным? (y/n, д/н): ", validator=YesNoValidator())
        is_central = YesNoValidator.is_yes(ans)

    if is_central:
        conn.execute("UPDATE catalog.warehouses SET is_central = FALSE WHERE is_central = TRUE")

    conn.execute(
        "INSERT INTO catalog.warehouses (city, address, label, is_central) VALUES (%s, %s, %s, %s)",
        (city, address, label, is_central),
    )

    if label:
        console.print(f"[green]Склад в городе {city} ({label}) добавлен [/green]")
    else:
        console.print(f"[green]Склад в городе {city} добавлен [/green]")


@command("edit warehouse", "редактировать склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def edit_warehouse(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (_id,))
        warehouse: Warehouse | None = cur.fetchone()

    if warehouse is None:
        render_error(f"Склад с ID {_id} не найден")
        return

    city_options = _get_cities_from_db()
    # Подставляем текущий текстовый город по умолчанию
    city = choice(message="Город склада:", options=city_options, default=warehouse.city)
    if city is None: return
    address = prompt(
        "Адрес: ", default=warehouse.address, validator=NonEmptyValidator()
    ).strip()
    label = (
        prompt("Метка (необязательно): ", default=warehouse.label or "").strip() or None
    )

    if warehouse.is_central:
        console.print("[yellow]Этот склад является центральным. Вы не можете убрать этот флаг, пока не назначите центральным другой склад.[/yellow]")
        is_central = True
    else:
        ans = prompt("Сделать этот склад центральным? (y/n, д/н): ", validator=YesNoValidator())
        is_central = YesNoValidator.is_yes(ans)

    if is_central and not warehouse.is_central:
        conn.execute("UPDATE catalog.warehouses SET is_central = FALSE WHERE is_central = TRUE")

    conn.execute(
        """UPDATE catalog.warehouses SET city = %s, address = %s, label = %s, is_central = %s
        WHERE id = %s""",
        (city, address, label, is_central, _id),
    )
    if label:
        console.print(f"[green]Склад в городе {city} ({label}) обновлен [/green]")
    else:
        console.print(f"[green]Склад в городе {city} обновлен [/green]")


@command("delete warehouse", "удалить склад", CATEGORY_WAREHOUSES, [ROLE_CATALOG_MANAGER])
def delete_warehouse(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute("SELECT * FROM catalog.warehouses WHERE id = %s", (_id,))
        warehouse: Warehouse | None = cur.fetchone()

    if warehouse is None:
        render_error(f"Склад с ID {_id} не найден")
        return

    if warehouse.is_central:
        render_error("Нельзя удалить центральный склад! Сначала назначьте другой склад центральным через 'edit warehouse'.")
        return

    _render_warehouse(warehouse)

    answer = prompt("Вы уверены? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        conn.execute("DELETE FROM catalog.warehouses WHERE id = %s", (_id,))
        if warehouse.label:
            console.print(
                f"[green]Склад в городе {warehouse.city} ({warehouse.label}) удален [/green]"
            )
        else:
            console.print(f"[green]Склад в городе {warehouse.city} удален [/green]")
