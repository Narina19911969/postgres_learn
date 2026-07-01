from dataclasses import dataclass
from datetime import datetime
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from auth import auth_user
from validators import YesNoValidator
from commands import command

CATEGORY_INVENTORY_READ = "Инвентарь: Чтение и Обработка"
ROLE_INVENTORY_MANAGER = "inventory_manager"


def _get_warehouses_options() -> list:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.id, c.name || ', ' || w.address || COALESCE(' (' || w.label || ')', '')
            FROM catalog.warehouses w
            JOIN catalog.cities c ON w.city = c.name
            ORDER BY w.id
        """)
        return cur.fetchall()


def _get_products_options() -> list:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, sku || ' - ' || name FROM catalog.products ORDER BY name")
        return cur.fetchall()


def _calculate_item_status(order_id: int, product_id: int, order_status: str, req_qty: int) -> str:
    conn = get_conn()
    
    if order_status == 'new':
        return "[yellow]ожидает обработки[/yellow]"

    with conn.cursor() as cur:
        cur.execute("""
            SELECT di.status 
            FROM inventory.delivery_items di
            WHERE di.order_id = %s AND di.product_id = %s
        """, (order_id, product_id))
        del_item = cur.fetchone()
        
        if del_item:
            if del_item[0] == 'shipped':
                return "[bold green]отгружено[/bold green]"
            elif del_item[0] == 'planned':
                return "[cyan]запланирована отгрузка[/cyan]"

        cur.execute("""
            SELECT quantity FROM inventory.order_reserves 
            WHERE order_id = %s AND product_id = %s
        """, (order_id, product_id))
        res_row = cur.fetchone()
        res_qty = res_row[0] if res_row else 0

        if res_qty >= req_qty:
            return f"[green]в резерве[/green] ({res_qty}/{req_qty} шт.)"

        cur.execute("""
            SELECT ti.status, t.id, c.name, t.arriving_at
            FROM inventory.transfer_items ti
            JOIN inventory.transfers t ON ti.transfer_id = t.id
            JOIN catalog.warehouses w ON t.src_warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            WHERE ti.order_id = %s AND ti.product_id = %s AND ti.status != 'received'
            ORDER BY t.id DESC
            LIMIT 1
        """, (order_id, product_id))
        trans_item = cur.fetchone()

        if trans_item:
            ti_status, t_id, src_city, arriving_at = trans_item
            if ti_status in ['planned', 'shipped']:
                time_str = f", прибытие: {arriving_at.strftime('%H:%M:%S')}" if arriving_at else ""
                return f"[magenta]в пути[/magenta] (Трансфер #{t_id} из г. {src_city}{time_str})"

    return f"[red]дефицит[/red] (в резерве только {res_qty}/{req_qty} шт.)"


@command("list orders new", "вывод списка новых свободных заказов", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def list_orders_new() -> None:
    conn = get_conn()
    table = Table(title="Новые заказы (ожидают обработки)", show_header=True, header_style="bold cyan")
    table.add_column("ID Заказа", justify="right")
    table.add_column("Сумма", justify="right")
    table.add_column("Склад отгрузки")
    table.add_column("Дата создания")
    table.add_column("Создатель")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.total_amount, c.name || ', ' || w.address, o.created_at, u.username
            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            JOIN auth.users u ON o.created_by = u.id
            WHERE o.status = 'new'
            ORDER BY o.id
        """)
        for r in cur.fetchall():
            table.add_row(str(r[0]), f"{r[1]:,.2f} руб.", r[2], r[3].strftime("%Y-%m-%d %H:%M"), r[4])
    console.print(table)


@command("list orders processing", "вывод списка всех заказов, находящихся в обработке", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def list_orders_processing() -> None:
    conn = get_conn()
    table = Table(title="Заказы в обработке", show_header=True, header_style="bold magenta")
    table.add_column("ID Заказа", justify="right")
    table.add_column("Статус")
    table.add_column("Сумма", justify="right")
    table.add_column("Склад отгрузки")
    table.add_column("Ответственный менеджер")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, c.name || ', ' || w.address, u.username
            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            JOIN auth.users u ON o.created_by = u.id
            WHERE o.status IN ('processing', 'pending', 'packing')
            ORDER BY o.id
        """)
        for r in cur.fetchall():
            table.add_row(str(r[0]), r[1], f"{r[2]:,.2f} руб.", r[3], r[4])
    console.print(table)


@command("list orders my", "вывод списка заказов, которые были обработаны текущим пользователем", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def list_orders_my() -> None:
    conn = get_conn()
    user_id = auth_user().id
    
    table = Table(title=f"Заказы, обрабатываемые мной (ID менеджера: {user_id})", show_header=True, header_style="bold green")
    table.add_column("ID Заказа", justify="right")
    table.add_column("Текущий статус", style="bold white")
    table.add_column("Сумма", justify="right")
    table.add_column("Склад отгрузки")
    table.add_column("Дата создания")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, c.name || ', ' || w.address, o.created_at
            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            WHERE o.created_by = %s
            ORDER BY o.id
        """, (user_id,))
        for r in cur.fetchall():
            table.add_row(str(r[0]), r[1], f"{r[2]:,.2f} руб.", r[3], r[4].strftime("%Y-%m-%d %H:%M"))
    console.print(table)


@command("mark order processing", "взять заказ из статуса 'new' в обработку менеджером инвентаря", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def mark_order_processing(order_id: str) -> None:
    conn = get_conn()
    o_id = int(order_id)
    user_id = auth_user().id

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, c.name || ', ' || w.address, u.username            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            JOIN auth.users u ON o.created_by = u.id
            WHERE o.id = %s
        """, (o_id,))
        order = cur.fetchone()

    if not order:
        render_error(f"Заказ с ID {o_id} не найден в системе.")
        return

    if order[1] != 'new':
        render_error(f"Невозможно взять заказ в обработку. Он имеет статус '{order[1]}', а ожидается 'new'.")
        return

    console.print(f"\n[bold yellow]Запрос на обслуживание заказа #{order[0]}[/bold yellow]")
    console.print(f" Склад отгрузки: {order[3]}")
    console.print(f" Сумма заказа:   {order[2]:,.2f} руб.")
    console.print(f" Создатель:      {order[4]}")
    
    ans = prompt("\nВы уверены, что хотите заявить права и взять этот заказ в обработку? (y/n, д/н): ", validator=YesNoValidator())
    
    if YesNoValidator.is_yes(ans):
        conn.execute("""
            UPDATE sales.orders 
            SET status = 'processing', created_by = %s 
            WHERE id = %s
        """, (user_id, o_id))
        console.print(f"[green]✓ Заказ #{o_id} успешно закреплен за вами и переведен в статус 'processing'.[/green]")

@command("show order", "детальный просмотр карточки заказа и вычисляемых статусов его позиций", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def show_order(order_id: str) -> None:
    conn = get_conn()
    o_id = int(order_id)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, o.created_at, c.name || ', ' || w.address, u.username
            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            JOIN auth.users u ON o.created_by = u.id
            WHERE o.id = %s
        """, (o_id,))
        order = cur.fetchone()

    if not order:
        render_error(f"Заказ с ID {o_id} не найден.")
        return

    card_table = Table(show_header=False, box=None, padding=(0, 2))
    card_table.add_column("Поле", style="bold cyan", width=20)
    card_table.add_column("Значение", style="white")
    
    card_table.add_row("ID Заказа", str(order[0]))
    card_table.add_row("Склад отгрузки", order[4])
    card_table.add_row("Статус заказа", order[1], style="bold magenta")
    card_table.add_row("Дата создания", order[3].strftime("%Y-%m-%d %H:%M:%S"))
    card_table.add_row("Кем создан (Sales)", order[5], style="yellow")
    card_table.add_row("Сумма по каталогу", f"{order[2]:,.2f} руб.", style="bold green")

    panel = Panel(card_table, expand=False, title=f"[bold green]Карточка Заказа #{order[0]}[/bold green]", border_style="green")
    console.print(panel)

    items_table = Table(title="Спецификация и статусы позиций", show_header=True, header_style="bold blue")
    items_table.add_column("Продукт / Наименование", min_width=25)
    items_table.add_column("Цена за шт.", justify="right", style="yellow")
    items_table.add_column("Количество", justify="right", style="green")
    items_table.add_column("Вычисляемый статус позиции", min_width=30)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT oi.product_id, p.sku || ' - ' || p.name, p.price, oi.quantity
            FROM sales.order_items oi
            JOIN catalog.products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
            ORDER BY p.name
        """, (o_id,))
        items = cur.fetchall()

    for p_id, prod_name, price, qty in items:
        dyn_status = _calculate_item_status(o_id, p_id, order[1], qty)
        items_table.add_row(prod_name, f"{price:.2f}", str(qty), dyn_status)
        
    console.print(items_table)


@command("view warehouse stock", "вывод остатков по конкретному складу", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def view_warehouse_stock() -> None:
    conn = get_conn()
    wh_options = _get_warehouses_options()
    
    if not wh_options:
        render_error("В системе нет созданных складов.")
        return
        
    wh_id = choice("Выберите склад для просмотра остатков:", options=wh_options)
    if wh_id is None: return

    wh_name = next(name for i, name in wh_options if i == wh_id)
    table = Table(title=f"Остатки на складе: {wh_name}", show_header=True, header_style="bold cyan")
    table.add_column("SKU / Товар", min_width=30)
    table.add_column("Свободный остаток (quantity)", justify="right", style="green")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.sku || ' - ' || p.name, s.quantity 
            FROM inventory.stock s
            JOIN catalog.products p ON s.product_id = p.id
            WHERE s.warehouse_id = %s AND s.quantity > 0
            ORDER BY p.name
        """, (wh_id,))
        stocks = cur.fetchall()

    if not stocks:
        console.print("[yellow]На данном складе сейчас нет свободных товаров.[/yellow]")
        return

    for prod, qty in stocks:
        table.add_row(prod, str(qty))
    console.print(table)


@command("view product stock", "вывод остатков конкретного продукта на всех складах", CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
def view_product_stock() -> None:
    conn = get_conn()
    prod_options = _get_products_options()
    
    if not prod_options:
        render_error("В каталоге нет товаров.")
        return
        
    p_id = choice("Выберите продукт для анализа остатков:", options=prod_options)
    if p_id is None: return

    prod_name = next(name for i, name in prod_options if i == p_id)
    table = Table(title=f"Распределение остатков товара: {prod_name}", show_header=True, header_style="bold yellow")
    table.add_column("Склад хранения (Город / Адрес)", min_width=35)
    table.add_column("Доступно штук", justify="right", style="green")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.name || ', ' || w.address || COALESCE(' (' || w.label || ')', ''), s.quantity
            FROM inventory.stock s
            JOIN catalog.warehouses w ON s.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            WHERE s.product_id = %s AND s.quantity > 0
            ORDER BY c.name
        """, (p_id,))
        stocks = cur.fetchall()

    if not stocks:
        console.print("[red]Данный товар полностью отсутствует на всех обычных складах системы.[/red]")
        return

    for wh_full_name, qty in stocks:
        table.add_row(wh_full_name, str(qty))
    console.print(table)
    
    
    
    
    
    
    

