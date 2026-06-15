from dataclasses import dataclass
from prompt_toolkit import prompt
from psycopg.rows import class_row
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_CATEGORIES


@dataclass
class ProductCategory:
    id: int
    name: str


@command("list categories", "список всех категорий", CATEGORY_CATEGORIES)
def list_categories() -> None:
    conn = get_conn()
    table = Table(title="Категории товаров", show_header=True, header_style="bold cyan")

    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Название категории", style="green", min_width=30)

    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT id, name FROM catalog.product_categories ORDER BY id")
        categories = cur.fetchall()

    for cat in categories:
        table.add_row(str(cat.id), cat.name)

    console.print(table)


@command("add category", "добавить категорию", CATEGORY_CATEGORIES)
def add_category() -> None:
    conn = get_conn()
    name = prompt("Название категории: ", validator=NonEmptyValidator()).strip()

    conn.execute(
        "INSERT INTO catalog.product_categories (name) VALUES (%s)",
        (name,)
    )
    console.print(f"[green]Категория '{name}' успешно добавлена.[/green]")


@command("edit category", "редактировать категорию", CATEGORY_CATEGORIES)
def edit_category(_id: str) -> None:
    conn = get_conn()

    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT id, name FROM catalog.product_categories WHERE id = %s", (_id,))
        cat = cur.fetchone()

    if cat is None:
        render_error(f"Категория с ID {_id} не найдена")
        return

    name = prompt("Новое название категории: ", default=cat.name, validator=NonEmptyValidator()).strip()

    conn.execute(
        "UPDATE catalog.product_categories SET name = %s WHERE id = %s",
        (name, _id)
    )
    console.print(f"[green]Категория обновлена на '{name}'.[/green]")


@command("delete category", "удалить категорию", CATEGORY_CATEGORIES)
def delete_category(_id: str) -> None:
    conn = get_conn()

    with conn.cursor(row_factory=class_row(ProductCategory)) as cur:
        cur.execute("SELECT id, name FROM catalog.product_categories WHERE id = %s", (_id,))
        cat = cur.fetchone()

    if cat is None:
        render_error(f"Категория с ID {_id} не найдена")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM catalog.products WHERE category_id = %s", (_id,))
        count = cur.fetchone()[0]

    if count > 0:
        render_error(f"Нельзя удалить категорию '{cat.name}', так как к ней привязано товаров: {count}.")
        return

    answer = prompt(f"Вы уверены, что хотите удалить категорию '{cat.name}'? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        conn.execute("DELETE FROM catalog.product_categories WHERE id = %s", (_id,))
        console.print(f"[green]Категория '{cat.name}' удалена.[/green]")