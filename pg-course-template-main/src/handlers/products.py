from dataclasses import dataclass
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command, CATEGORY_PRODUCTS
from decimal import Decimal

class SkuValidator(NonEmptyValidator):
    def validate(self, document):
        super().validate(document)
        if len(document.text) > 30:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Артикул (SKU) не может быть длиннее 30 символов.")


class PriceValidator(NonEmptyValidator):
    def validate(self, document):
        super().validate(document)
        try:
            price = Decimal(document.text)
            if price <= 0:
                raise ValueError
        except ValueError:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Цена должна быть числом больше 0.")


@dataclass
class Product:
    id: int
    sku: str
    name: str
    price: Decimal
    category_id: int


def _render_product(product: Product) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM catalog.product_categories WHERE id = %s", (product.category_id,))
        row = cur.fetchone()
        category_name = row[0] if row else "Неизвестно"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")

    table.add_row("ID", str(product.id))
    table.add_row("Артикул (SKU)", product.sku)
    table.add_row("Наименование", product.name)
    table.add_row("Цена", f"{product.price:,.2f} руб.")
    table.add_row("Категория", f"{category_name} (ID: {product.category_id})")

    panel = Panel(table, expand=False, title=f"[bold green]Товар #{product.id}[/bold green]", border_style="green")
    console.print(panel)


@command("list products", "список всех товаров", CATEGORY_PRODUCTS)
def list_products() -> None:
    conn = get_conn()
    table = Table(title="Каталог товаров", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("SKU (Артикул)", style="magenta", width=15)
    table.add_column("Название товара", style="white", min_width=25)
    table.add_column("Цена", style="green", justify="right", width=12)
    table.add_column("Категория", style="yellow", min_width=15)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.price, c.name 
            FROM catalog.products p
            JOIN catalog.product_categories c ON p.category_id = c.id
            ORDER BY p.id
        """)
        products = cur.fetchall()

    for p_id, sku, name, price, cat_name in products:
        table.add_row(str(p_id), sku, name, f"{price:.2f}", cat_name)
    console.print(table)


@command("show product", "информация о товаре", CATEGORY_PRODUCTS)
def show_product(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("SELECT id, sku, name, price, category_id FROM catalog.products WHERE id = %s", (_id,))
        product = cur.fetchone()

    if product is None:
        render_error(f"Товар с ID {_id} не найден")
        return
    _render_product(product)


@command("add product", "добавить товар", CATEGORY_PRODUCTS)
def add_product() -> None:
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM catalog.product_categories ORDER BY name")
        categories_data = cur.fetchall()

    if not categories_data:
        render_error("В системе нет ни одной категории! Сначала добавьте категорию через 'add category'.")
        return

    category_map = {name: cat_id for cat_id, name in categories_data}
    category_names = list(category_map.keys())

    category_completer = WordCompleter(category_names, ignore_case=True, sentence=True)
    category_validator = ChoiceValidator(category_names, message="Выберите категорию из списка.")

    sku = prompt("Артикул (SKU, до 30 симв.): ", validator=SkuValidator()).strip()
    name = prompt("Название товара: ", validator=NonEmptyValidator()).strip()
    price_str = prompt("Цена товара: ", validator=PriceValidator()).strip()

    selected_category_name = prompt("Категория товара (Tab для выбора): ", validator=category_validator,
                                    completer=category_completer).strip()
    category_id = category_map[selected_category_name]

    conn.execute(
        "INSERT INTO catalog.products (sku, name, price, category_id) VALUES (%s, %s, %s, %s)",
        (sku, name, Decimal(price_str), category_id),
    )
    console.print(f"[green]Товар '{name}' ({sku}) успешно добавлен в категорию '{selected_category_name}'.[/green]")


@command("edit product", "редактировать товар", CATEGORY_PRODUCTS)
def edit_product(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("SELECT id, sku, name, price, category_id FROM catalog.products WHERE id = %s", (_id,))
        product = cur.fetchone()

    if product is None:
        render_error(f"Товар с ID {_id} не найден")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM catalog.product_categories ORDER BY name")
        categories_data = cur.fetchall()

    category_map = {name: cat_id for cat_id, name in categories_data}
    category_names = list(category_map.keys())

    category_completer = WordCompleter(category_names, ignore_case=True, sentence=True)
    category_validator = ChoiceValidator(category_names, message="Выберите категорию из списка.")

    current_category_name = ""
    for name, cat_id in category_map.items():
        if cat_id == product.category_id:
            current_category_name = name
            break

    sku = prompt("Артикул (SKU): ", default=product.sku, validator=SkuValidator()).strip()
    name = prompt("Название товара: ", default=product.name, validator=NonEmptyValidator()).strip()
    price_str = prompt("Цена товара: ", default=str(product.price), validator=PriceValidator()).strip()

    selected_category_name = prompt("Категория товара: ", default=current_category_name, validator=category_validator,
                                    completer=category_completer).strip()
    category_id = category_map[selected_category_name]

    conn.execute(
        "UPDATE catalog.products SET sku = %s, name = %s, price = %s, category_id = %s WHERE id = %s",
        (sku, name, Decimal(price_str), category_id, _id),
    )
    console.print(f"[green]Товар #{_id} успешно обновлен.[/green]")


@command("delete product", "удалить товар", CATEGORY_PRODUCTS)
def delete_product(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute("SELECT id, sku, name, price, category_id FROM catalog.products WHERE id = %s", (_id,))
        product = cur.fetchone()

    if product is None:
        render_error(f"Товар с ID {_id} не найден")
        return

    _render_product(product)
    answer = prompt("Вы уверены, что хотите удалить этот товар? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        conn.execute("DELETE FROM catalog.products WHERE id = %s", (_id,))
        console.print(f"[green]Товар {product.name} удален из каталога.[/green]")
