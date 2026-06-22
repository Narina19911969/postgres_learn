from dataclasses import dataclass
from datetime import datetime
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import choice
from psycopg.rows import class_row
from rich.panel import Panel
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import ChoiceValidator, NonEmptyValidator, YesNoValidator
from commands import command
from auth import ROLE_SALES_MANAGER, _USER

CATEGORY_ORDERS = "Управление заказами"


@dataclass
class Order:
    id: int
    status: str
    total_amount: float
    created_at: datetime
    warehouse_id: int


@dataclass
class OrderItem:
    order_id: int
    product_id: int
    quantity: int


class QuantityValidator(NonEmptyValidator):
    def validate(self, document):
        super().validate(document)
        try:
            qty = int(document.text)
            if qty <= 0:
                raise ValueError
        except ValueError:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Количество должно быть целым числом строго больше 0.")

def _render_order(order: Order) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT city, address, label FROM catalog.warehouses WHERE id = %s", (order.warehouse_id,))
        wh = cur.fetchone()
        if wh:
            wh_name = f"{wh[0]}, {wh[1]}" + (f" ({wh[2]})" if wh[2] else "")
        else:
            wh_name = "Неизвестный склад"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan", width=15)
    table.add_column("Значение", style="white")

    table.add_row("ID Заказа", str(order.id))
    table.add_row("Статус", order.status, style="bold magenta")
    table.add_row("Сумма заказа", f"{order.total_amount:,.2f} руб.", style="bold green")
    table.add_row("Дата создания", order.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("Склад отгрузки", wh_name)

    panel = Panel(table, expand=False, title=f"[bold green]Заказ #{order.id}[/bold green]", border_style="green")
    console.print(panel)


def recalculate_order_total(order_id: int) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(oi.quantity * p.price), 0)
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
        """, (order_id,))
        new_total = cur.fetchone()[0]

        cur.execute("UPDATE sales.orders SET total_amount = %s WHERE id = %s", (new_total, order_id))


def interactive_add_items(order_id: int) -> None:
    conn = get_conn()
    while True:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, sku, name, price FROM catalog.products 
                WHERE id NOT IN (SELECT product_id FROM sales.order_items WHERE order_id = %s)
                ORDER BY name
            """, (order_id,))
            available_products = cur.fetchall()

        if not available_products:
            console.print("[yellow]Все доступные товары из каталога уже добавлены в этот заказ.[/yellow]")
            break

        p_map = {}
        p_options = []
        for p_id, sku, name, price in available_products:
            opt_str = f"{sku} - {name} ({price:.2f} руб.)"
            p_options.append(opt_str)
            p_map[opt_str] = p_id

        p_completer = WordCompleter(p_options, ignore_case=True, sentence=True)
        p_validator = ChoiceValidator(p_options, message="Выберите доступный товар с помощью автодополнения.")

        selected_p = prompt("Выберите товар для добавления (Tab): ", validator=p_validator, completer=p_completer).strip()
        product_id = p_map[selected_p]

        qty_str = prompt("Укажите количество: ", validator=QuantityValidator()).strip()
        quantity = int(qty_str)

        conn.execute(
            "INSERT INTO sales.order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)",
            (order_id, product_id, quantity)
        )
        console.print("[green]Товар успешно добавлен в текущий заказ.[/green]")

        recalculate_order_total(order_id)

        ans = prompt("Хотите добавить еще один товар в этот заказ? (y/n, д/н): ", validator=YesNoValidator())
        if not YesNoValidator.is_yes(ans):
            break


@command("add order", "создать новый заказ (интерактивно)", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def add_order() -> None:
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute("SELECT id, city, address, label FROM catalog.warehouses ORDER BY id")
        wh_data = cur.fetchall()

    if not wh_data:
        render_error("В системе нет складов! Сначала добавьте склад.")
        return

    wh_options = []
    for w_id, city, addr, label in wh_data:
        lbl = f" ({label})" if label else ""
        wh_options.append((w_id, f"{city}, {addr}{lbl}"))

    warehouse_id = choice(
        message="Выберите склад отгрузки заказа из списка:",
        options=wh_options
    )

    if warehouse_id is None:
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sales.orders (warehouse_id, status, total_amount, created_by) 
            VALUES (%s, 'unpublished', 0.00, %s) 
            RETURNING id
            """,
            (warehouse_id, _USER)
        )
        row = cur.fetchone()
        order_id = row[0]

    console.print(f"[green]Заказ #{order_id} успешно инициализирован в статусе 'unpublished'.[/green]")
    interactive_add_items(order_id)

@command("edit order", "редактировать склад отгрузки заказа", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def edit_order(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("SELECT id, status, total_amount, created_at, warehouse_id FROM sales.orders WHERE id = %s", (_id,))
        order = cur.fetchone()

    if order is None:
        render_error(f"Заказ с ID {_id} не найден")
        return

    console.print(f"[yellow]Статус заказа: '{order.status}' (изменение статуса при редактировании запрещено).[/yellow]")

    with conn.cursor() as cur:
        cur.execute("SELECT id, city, address, label FROM catalog.warehouses ORDER BY id")
        wh_data = cur.fetchall()

    wh_options = []
    for w_id, city, addr, label in wh_data:
        lbl = f" ({label})" if label else ""
        wh_options.append((w_id, f"{city}, {addr}{lbl}"))

    warehouse_id = choice(
        message="Выберите новый склад отгрузки:",
        options=wh_options,
        default=order.warehouse_id
    )

    if warehouse_id is None:
        return

    conn.execute("UPDATE sales.orders SET warehouse_id = %s WHERE id = %s", (warehouse_id, _id))
    console.print(f"[green]Заказ #{_id} успешно обновлен.[/green]")

@command("delete order", "удалить заказ", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def delete_order(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("SELECT id, status, total_amount, created_at, warehouse_id FROM sales.orders WHERE id = %s", (_id,))
        order = cur.fetchone()

    if order is None:
        render_error(f"Заказ с ID {_id} не найден")
        return

    _render_order(order)
    answer = prompt("Вы уверены, что хотите удалить этот заказ? (y/n, д/н): ", validator=YesNoValidator())

    if YesNoValidator.is_yes(answer):
        conn.execute("DELETE FROM sales.orders WHERE id = %s", (_id,))
        console.print(f"[green]Заказ #{_id} успешно удален.[/green]")


@command("add order_item", "добавить позицию в существующий заказ", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def add_order_item(order_id: str) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM sales.orders WHERE id = %s)", (order_id,))
        if not cur.fetchone()[0]:
            render_error(f"Заказ с ID {order_id} не найден.")
            return

    interactive_add_items(int(order_id))
@command("edit order_item", "изменить количество товара в позиции заказа", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def edit_order_item(order_id: str) -> None:
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT oi.product_id, p.sku, p.name, oi.quantity 
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
            ORDER BY p.name
        """, (order_id,))
        items = cur.fetchall()

    if not items:
        render_error(f"В заказе #{order_id} нет позиций для редактирования.")
        return

    item_options = []
    for p_id, sku, name, qty in items:
        item_options.append((p_id, f"{sku} - {name} (Текущее кол-во: {qty} шт.)"))

    product_id = choice(
        message="Выберите товарную позицию для изменения количества:",
        options=item_options
    )

    if product_id is None:
        return

    current_qty = 1
    for p_id, _, _, qty in items:
        if p_id == product_id:
            current_qty = qty
            break

    new_qty_str = prompt("Укажите новое количество: ", default=str(current_qty), validator=QuantityValidator()).strip()
    new_quantity = int(new_qty_str)

    conn.execute("""
        UPDATE sales.order_items 
        SET quantity = %s 
        WHERE order_id = %s AND product_id = %s
    """, (new_quantity, order_id, product_id))

    console.print(f"[green]Количество товара успешно изменено на {new_quantity}.[/green]")
    recalculate_order_total(int(order_id))


@command("delete order_item", "удалить товарную позицию из заказа", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def delete_order_item(order_id: str) -> None:
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT oi.product_id, p.sku, p.name, oi.quantity 
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
            ORDER BY p.name
        """, (order_id,))
        items = cur.fetchall()

    if not items:
        render_error(f"В заказе #{order_id} нет доступных позиций.")
        return

    item_options = []
    for p_id, sku, name, qty in items:
        item_options.append((p_id, f"{sku} - {name} ({qty} шт.)"))

    product_id = choice(
        message="Выберите товарную позицию для удаления из заказа:",
        options=item_options
    )

    if product_id is None:
        return

    answer = prompt("Вы уверены, что хотите удалить эту строку из заказа? (y/n, д/н): ", validator=YesNoValidator())
    if YesNoValidator.is_yes(answer):
        conn.execute("""
            DELETE FROM sales.order_items 
            WHERE order_id = %s AND product_id = %s
        """, (order_id, product_id))

        console.print(f"[green]Товар успешно удален из спецификации заказа.[/green]")
        recalculate_order_total(int(order_id))

@command("list orders", "список всех заказов", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def list_orders() -> None:
    conn = get_conn()
    table = Table(title="Список заказов", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Статус", style="magenta", width=15)
    table.add_column("Сумма", style="green", justify="right", width=15)
    table.add_column("Дата создания", style="white", width=20)
    table.add_column("Склад (Город)", style="yellow", min_width=20)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, o.created_at, w.city 
            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            ORDER BY o.id
        """)
        orders = cur.fetchall()

    for o_id, status, total, created, city in orders:
        table.add_row(str(o_id), status, f"{total:.2f}", created.strftime("%Y-%m-%d %H:%M"), city)
    console.print(table)


@command("show order", "информация о заказе и его составе", CATEGORY_ORDERS, [ROLE_SALES_MANAGER])
def show_order(_id: str) -> None:
    conn = get_conn()
    with conn.cursor(row_factory=class_row(Order)) as cur:
        cur.execute("SELECT id, status, total_amount, created_at, warehouse_id FROM sales.orders WHERE id = %s", (_id,))
        order = cur.fetchone()

    if order is None:
        render_error(f"Заказ с ID {_id} не найден")
        return

    _render_order(order)

    table = Table(title="Содержимое заказа", show_header=True, header_style="bold blue")
    table.add_column("SKU", style="magenta", width=15)
    table.add_column("Товар", style="white", min_width=25)
    table.add_column("Количество", style="green", justify="right", width=12)
    table.add_column("Цена за шт.", style="yellow", justify="right", width=12)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.sku, p.name, oi.quantity, p.price
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
            ORDER BY p.name
        """, (_id,))
        items = cur.fetchall()

    for sku, name, qty, price in items:
        table.add_row(sku, name, str(qty), f"{price:.2f}")
    console.print(table)
