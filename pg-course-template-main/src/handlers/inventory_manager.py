from dataclasses import dataclass
from datetime import datetime
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from rich.table import Table
from rich.panel import Panel

from console import console, render_error
from db import get_conn
from auth import auth_user
from validators import YesNoValidator, NonEmptyValidator
from commands import command
from psycopg.errors import SerializationFailure

CATEGORY_INVENTORY_READ = "Инвентарь: Чтение и Обработка"
ROLE_INVENTORY_MANAGER = "inventory_manager"
CATEGORY_INVENTORY_MGMT = "Управление инвентарем"

class QuantityValidator(NonEmptyValidator):
    def validate(self, document):
        super().validate(document)
        try:
            val = int(document.text)
            if val <= 0: raise ValueError
        except ValueError:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Количество должно быть целым числом строго больше 0.")




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


@command("process_order", "интерактивная многоступенчатая обработка позиций заказа", CATEGORY_INVENTORY_MGMT, [ROLE_INVENTORY_MANAGER])
def process_order(order_id: str) -> None:
    conn = get_conn()
    o_id = int(order_id)
    user_id = auth_user().id

    with conn.cursor() as cur:
        cur.execute("SELECT warehouse_id FROM sales.orders WHERE id = %s", (o_id,))
        o_row = cur.fetchone()
        if not o_row or o_row[0] is None:
            render_error(f"Заказ #{o_id} не найден или у него не указан склад назначения.")
            return

        target_wh_id = int(o_row[0])

        cur.execute("SELECT product_id, quantity FROM sales.order_items WHERE order_id = %s", (o_id,))
        items = cur.fetchall()

    if not items:
        render_error(f"В заказе #{o_id} нет позиций товаров.")
        return

    console.print(f"\n[bold blue]=== Мастер обработки Заказа #{o_id} ===[/bold blue]")

    for item in items:
        p_id = int(item[0])
        req_qty = int(item[1])

        while True:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT quantity FROM inventory.stock WHERE warehouse_id = %s AND product_id = %s",
                    (target_wh_id, p_id)
                )
                s_row = cur.fetchone()
                local_stock = int(s_row[0]) if s_row and s_row[0] is not None else 0

            console.print(
                f"\n[bold yellow]Товар ID {p_id} | Требуется: {req_qty} шт. | На целевом складе: {local_stock} шт.[/bold yellow]")

            options = []
            if local_stock >= req_qty:
                options.append((1, f"Добавить в резерв с текущего склада ({req_qty} шт.)"))
            else:
                options.append((1,
                                f"[dim]Добавить в резерв с текущего склада (Недостаточно стока: {local_stock}/{req_qty})[/dim]"))
            options.append((2, "Искать на других складах (Создать межскладской трансфер)"))
            options.append((None, "--> Выйти из обработки заказа <--"))

            act_choice = choice("Выберите действие:", options=options)
            if act_choice is None:
                console.print("[yellow]Обработка заказа прервана менеджером.[/yellow]")
                return

            if act_choice == 1:
                if local_stock < req_qty:
                    render_error("Невозможно выбрать эту опцию при дефиците товара на складе!")
                    continue
                ans = prompt("Подтвердить резервирование? (y/n): ", validator=YesNoValidator())
                if not YesNoValidator.is_yes(ans):
                    continue

                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT quantity FROM inventory.stock WHERE warehouse_id = %s AND product_id = %s FOR UPDATE",
                                (target_wh_id, p_id)
                            )
                            fresh_row = cur.fetchone()
                            f_stock = int(fresh_row[0]) if fresh_row and fresh_row[0] is not None else 0

                            if f_stock < req_qty:
                                render_error("Ошибка гонки данных: свободный остаток изменился!")
                                return

                            cur.execute(
                                "UPDATE inventory.stock SET quantity = quantity - %s WHERE warehouse_id = %s AND product_id = %s",
                                (req_qty, target_wh_id, p_id)
                            )

                            cur.execute("""
                                INSERT INTO inventory.order_reserves (order_id, warehouse_id, product_id, quantity)
                                VALUES (%s, %s, %s, %s)
                            """, (o_id, target_wh_id, p_id, req_qty))

                    console.print("[green]✓ Товар успешно перенесен в резерв текущего склада.[/green]")
                    break
                except Exception as e:
                    render_error(f"Ошибка транзакции резервирования: {e}")
                    return

            elif act_choice == 2:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT s.warehouse_id, c.name || ' (' || w.address || ') [В наличии: ' || s.quantity || ' шт.]'
                        FROM inventory.stock s
                        JOIN catalog.warehouses w ON s.warehouse_id = w.id
                        JOIN catalog.cities c ON w.city = c.name
                        WHERE s.product_id = %s AND s.warehouse_id != %s AND s.quantity >= %s
                    """, (p_id, target_wh_id, req_qty))
                    donors = cur.fetchall()

                if not donors:
                    render_error("Ни на одном удаленном складе системы нет нужного объема товара!")
                    continue

                formatted_options = []
                for d in donors:
                    wh_donor_id = int(d[0])
                    wh_label = str(d[1])
                    formatted_options.append((wh_donor_id, wh_label))
                formatted_options.append((0, "<-- Вернуться назад к выбору действий"))

                selected_src_wh = choice("Выберите склад-отправитель для трансфера:", options=formatted_options)
                if selected_src_wh == 0 or selected_src_wh is None:
                    continue  # Логика возврата к предыдущему выбору шага по ТЗ

                ans = prompt(f"Заказать трансфер {req_qty} шт. с выбранного склада? (y/n): ",
                             validator=YesNoValidator())
                if not YesNoValidator.is_yes(ans):
                    continue

                insert_tr_item_transaction(conn, user_id, selected_src_wh, p_id, req_qty,
                               target_wh_id)

    console.print("\n[bold green]=== Попозиционная обработка заказа менеджером успешно завершена! ===[/bold green]")


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

        if res_qty > 0:
            return "[green]в резерве[/green]"

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

    return "[red]дефицит[/red] (требуется перемещение)"

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


@command("mark order processing",
         "взять заказ из статуса 'new' в обработку (двухфазный паттерн без блокировок во время инпута)",
         CATEGORY_INVENTORY_MGMT, [ROLE_INVENTORY_MANAGER])
def mark_order_processing(order_id: str) -> None:
    conn = get_conn()
    o_id = int(order_id)
    user_id = auth_user().id

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.id, o.status, o.total_amount, c.name || ', ' || w.address, u.username
            FROM sales.orders o
            JOIN catalog.warehouses w ON o.warehouse_id = w.id
            JOIN catalog.cities c ON w.city = c.name
            JOIN auth.users u ON o.created_by = u.id
            WHERE o.id = %s
        """, (o_id,))
        order = cur.fetchone()

    if not order:
        render_error(f"Заказ с ID {o_id} не найден в системе.")
        return

    status = order[1]
    if status != 'new':
        render_error(f"Невозможно взять заказ в работу. Его текущий статус: '{status}', ожидался 'new'.")
        return

    console.print(f"\n[bold yellow]Запрос на обслуживание заказа #{order[0]}[/bold yellow]")
    console.print(f" Склад отгрузки: {order[3]}")
    console.print(f" Сумма заказа:   {order[2]:,.2f} руб.")
    console.print(f" Создатель:      {order[4]}")

    ans = prompt("\nВы уверены, что хотите заявить права и взять этот заказ в обработку? (y/n, д/н): ",
                 validator=YesNoValidator())

    if not YesNoValidator.is_yes(ans):
        console.print("[yellow]Операция отменена менеджером.[/yellow]")
        return

    try:

        with conn.transaction():
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT status FROM sales.orders o WHERE id = %s FOR UPDATE OF o
                """, (o_id,))
                lock_row = cur.fetchone()

                if not lock_row or lock_row[0] != 'new':
                    render_error(
                        "[red]Ошибка гонки данных: пока вы подтверждали операцию, другой менеджер уже перехватил этот заказ![/red]")
                    return

                cur.execute("""
                    UPDATE sales.orders 
                    SET status = 'processing', created_by = %s 
                    WHERE id = %s
                """, (user_id, o_id))

        console.print(f"[green]✓ Заказ #{o_id} успешно заблокирован и закреплен за вами в СУБД.[/green]")

    except Exception as e:
        render_error(f"Критическая ошибка транзакции: {e}")


@command("start shipping", "перевести перемещение из статуса planned в статус shipping для начала отгрузки воркером",
         CATEGORY_INVENTORY_MGMT, [ROLE_INVENTORY_MANAGER])
def start_shipping(transfer_id: str) -> None:
    conn = get_conn()
    t_id = int(transfer_id)

    try:
        with conn.transaction():
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT status FROM inventory.transfers 
                    WHERE id = %s 
                    FOR UPDATE
                """, (t_id,))
                row = cur.fetchone()

                if not row:
                    render_error(f"Накладная межскладского перемещения #{t_id} не найдена.")
                    return

                status = row[0]
                if status != 'planned':
                    render_error(
                        f"Невозможно запустить отгрузку. Текущий статус перемещения: '{status}', ожидался 'planned'.")
                    return

                cur.execute("""
                    UPDATE inventory.transfers 
                    SET status = 'shipping' 
                    WHERE id = %s
                """, (t_id,))

        console.print(f"[bold green]✓ Статус перемещения #{t_id} успешно изменен на 'shipping'.[/bold green]")
        console.print("[green]Накладная передана в работу кладовщикам (worker) для попозиционной погрузки.[/green]")

    except Exception as e:
        render_error(f"Критическая ошибка транзакции: {e}")

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


@command("view warehouse stock", "вывод остатков по конкретному складу", CATEGORY_INVENTORY_READ,
         [ROLE_INVENTORY_MANAGER])
def view_warehouse_stock() -> None:
    conn = get_conn()
    wh_options = _get_warehouses_options()

    if not wh_options:
        render_error("В системе нет созданных складов.")
        return

    wh_id = choice("Выберите склад для просмотра остатков:", options=wh_options)
    if wh_id is None: return

    wh_name = next(name for i, name in wh_options if i == wh_id)
    table = Table(title=f"Баланс товаров на складе: {wh_name}", show_header=True, header_style="bold cyan")
    table.add_column("SKU / Товар", min_width=30)
    table.add_column("Доступно", justify="right", style="green")
    table.add_column("В резерве", justify="right", style="yellow")
    table.add_column("Всего", justify="right", style="bold white")

    with conn.cursor() as cur:
        cur.execute("""
            WITH current_stock AS (
                SELECT product_id, quantity 
                FROM inventory.stock 
                WHERE warehouse_id = %s
            ),
            current_reserves AS (
                SELECT product_id, SUM(quantity) AS reserved_qty 
                FROM inventory.order_reserves 
                WHERE warehouse_id = %s
                GROUP BY product_id
            )
            SELECT 
                p.sku || ' - ' || p.name AS product_info,
                COALESCE(s.quantity, 0) AS available_qty,
                COALESCE(r.reserved_qty, 0) AS reserved_qty,
                (COALESCE(s.quantity, 0) + COALESCE(r.reserved_qty, 0)) AS total_qty
            FROM catalog.products p
            LEFT JOIN current_stock s ON s.product_id = p.id
            LEFT JOIN current_reserves r ON r.product_id = p.id
            ORDER BY p.name;
        """, (wh_id, wh_id))
        stocks = cur.fetchall()

    for prod, available, reserved, total in stocks:
        if total == 0:
            table.add_row(f"[dim]{prod}[/dim]", "[dim]0[/dim]", "[dim]0[/dim]", "[dim]0[/dim]")
        else:
            table.add_row(prod, str(available), str(reserved), str(total))

    console.print(table)


@command("view product stock", "вывод остатков конкретного продукта на всех складах (конвейер подзапросов)",
         CATEGORY_INVENTORY_READ, [ROLE_INVENTORY_MANAGER])
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
    table.add_column("Доступно", justify="right", style="green")
    table.add_column("В резерве", justify="right", style="yellow")
    table.add_column("Всего", justify="right", style="bold white")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                wh_view.warehouse_info,
                calc_total.available_qty,
                calc_total.reserved_qty,
                calc_total.total_qty
            FROM (
                SELECT 
                    w.id AS wh_id,
                    c.name || ', ' || w.address || COALESCE(' (' || w.label || ')', '') AS warehouse_info
                FROM catalog.warehouses w
                JOIN catalog.cities c ON w.city = c.name
            ) wh_view
            JOIN (
                SELECT 
                    raw_data.wh_id,
                    raw_data.available_qty,
                    raw_data.reserved_qty,
                    (raw_data.available_qty + raw_data.reserved_qty) AS total_qty
                FROM (
                    SELECT 
                        w_sub.id AS wh_id,
                        COALESCE(
                            (SELECT quantity FROM inventory.stock 
                             WHERE warehouse_id = w_sub.id AND product_id = %s), 0
                        ) AS available_qty,
                        COALESCE(
                            (SELECT SUM(quantity) FROM inventory.order_reserves 
                             WHERE warehouse_id = w_sub.id AND product_id = %s), 0
                        ) AS reserved_qty
                    FROM catalog.warehouses w_sub
                ) raw_data
            ) calc_total ON wh_view.wh_id = calc_total.wh_id
            WHERE calc_total.total_qty > 0
            ORDER BY calc_total.available_qty DESC, wh_view.warehouse_info;
        """, (p_id, p_id))
        stocks = cur.fetchall()

    if not stocks:
        console.print("[red]Данный товар сейчас полностью отсутствует на всех складах системы.[/red]")
        return

    for wh_name, available, reserved, total in stocks:
        table.add_row(wh_name, str(available), str(reserved), str(total))

    console.print(table)

def insert_tr_item_transaction(conn, user_id,  src_id, chosen_product_id, req_qty,
                               dst_id) -> None:
    try:
        with conn.transaction():
            with conn.cursor() as cur:

                cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")

                cur.execute("""
                    SELECT quantity FROM inventory.stock 
                    WHERE warehouse_id = %s AND product_id = %s FOR UPDATE
                """, (src_id, chosen_product_id))
                stock_row = cur.fetchone()

                actual_stock = stock_row[0] if stock_row else 0
                if actual_stock < req_qty:
                    render_error(
                        "[red]Ошибка транзакции: за время подтверждения свободный остаток товара изменился![/red]")
                    return

                cur.execute("""
                    SELECT id FROM inventory.transfers 
                    WHERE src_warehouse_id = %s AND dst_warehouse_id = %s AND status = 'planned'
                    FOR SHARE
                """, (src_id, dst_id))
                t_row = cur.fetchone()
                t_id = t_row[0] if t_row else None

                if not t_id:
                    cur.execute("""
                        INSERT INTO inventory.transfers (src_warehouse_id, dst_warehouse_id, status)
                        VALUES (%s, %s, 'planned') RETURNING id
                    """, (src_id, dst_id))
                    t_id = cur.fetchone()[0]

                cur.execute("""
                    SELECT id FROM inventory.transfer_items
                    WHERE transfer_id = %s AND created_by = %s AND product_id = %s AND order_id IS NULL
                """, (t_id, user_id, chosen_product_id))
                existing_item = cur.fetchone()

                cur.execute("""
                    UPDATE inventory.stock SET quantity = quantity - %s 
                    WHERE warehouse_id = %s AND product_id = %s
                """, (req_qty, src_id, chosen_product_id))

                if existing_item:
                    ti_id = existing_item[0]
                    cur.execute("""
                        UPDATE inventory.transfer_items 
                        SET quantity = quantity + %s 
                        WHERE id = %s
                    """, (req_qty, ti_id))
                else:
                    cur.execute("""
                        INSERT INTO inventory.transfer_items (transfer_id, product_id, quantity, status, created_by, order_id)
                        VALUES (%s, %s, %s, 'planned', %s, NULL)
                    """, (t_id, chosen_product_id, req_qty, user_id))

        console.print(f"[bold green]✓ Операция успешно завершена! {req_qty} шт. добавлены в ...[/bold green]")

    except SerializationFailure:
        render_error(
            "[red]Ошибка гонки данных: параллельный менеджер изменил накладные на этом маршруте. Пожалуйста, повторите попытку.[/red]")
    except Exception as e:
        render_error(f"Критическая ошибка при записи в БД: {e}")

@command("add transfer items", "интерактивное добавление товаров в перемещение (изоляция SERIALIZABLE)",
         CATEGORY_INVENTORY_MGMT, [ROLE_INVENTORY_MANAGER])
def add_transfer_items() -> None:
    conn = get_conn()
    user_id = auth_user().id

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT w1.id, c1.name || ' (' || w1.address || ')'
            FROM inventory.routes r
            JOIN catalog.warehouses w1 ON w1.city = (SELECT name FROM catalog.cities WHERE id = r.from_city_id)
            JOIN catalog.cities c1 ON w1.city = c1.name
        """)
        src_warehouses = cur.fetchall()

    if not src_warehouses:
        render_error("В системе нет доступных складов отправления на основе маршрутов.")
        return

    src_id = choice("Шаг 1: Выберите склад ОТПРАВЛЕНИЯ:", options=src_warehouses)
    if src_id is None: return

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT w2.id, c2.name || ' (' || w2.address || ')'
            FROM inventory.routes r
            JOIN catalog.warehouses w1 ON w1.city = (SELECT name FROM catalog.cities WHERE id = r.from_city_id)
            JOIN catalog.warehouses w2 ON w2.city = (SELECT name FROM catalog.cities WHERE id = r.to_city_id)
            JOIN catalog.cities c2 ON w2.city = c2.name
            WHERE w1.id = %s
        """, (src_id,))
        dst_warehouses = cur.fetchall()

    if not dst_warehouses:
        render_error("Для выбранного склада нет доступных направлений получения.")
        return

    dst_id = choice("Шаг 2: Выберите склад ПОЛУЧЕНИЯ:", options=dst_warehouses)
    if dst_id is None: return

    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.id, p.sku || ' - ' || p.name, s.quantity 
            FROM inventory.stock s
            JOIN catalog.products p ON s.product_id = p.id
            WHERE s.warehouse_id = %s AND s.quantity > 0
        """, (src_id,))
        stock_items = cur.fetchall()

    if not stock_items:
        render_error("На складе отправления нет доступных товаров для перемещения.")
        return

    options = [(p[0], f"{p[1]} [Доступно: {p[2]} шт.]") for p in stock_items]
    chosen_product_id = choice("Шаг 3: Выберите товар для перемещения:", options=options)
    if chosen_product_id is None: return

    target_item = next(p for p in stock_items if p[0] == chosen_product_id)
    available_qty = target_item[2]

    qty_str = prompt(f"Шаг 4: Укажите количество товара для перемещения (макс. {available_qty}): ",
                     validator=QuantityValidator()).strip()
    req_qty = int(qty_str)

    if req_qty > available_qty:
        render_error("Ошибка бизнес-логики: Запрошено больше, чем есть на свободном остатке склада!")
        return

    ans = prompt(f"Шаг 5: Подтверждаете добавление {req_qty} шт. в накладную? (y/n): ", validator=YesNoValidator())
    if not YesNoValidator.is_yes(ans):
        console.print("[yellow]Операция полностью отменена. База данных не затрагивалась.[/yellow]")
        return

    insert_tr_item_transaction(conn, user_id, src_id, chosen_product_id, req_qty,
                               dst_id)


@command("remove transfer items", "интерактивное удаление товаров из перемещения (двухфазный паттерн без инпутов)",
         CATEGORY_INVENTORY_MGMT, [ROLE_INVENTORY_MANAGER])
def remove_transfer_items() -> None:
    conn = get_conn()
    user_id = auth_user().id
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT t.id, c1.name || ' -> ' || c2.name 
            FROM inventory.transfers t
            JOIN inventory.transfer_items ti ON ti.transfer_id = t.id
            JOIN catalog.warehouses w1 ON t.src_warehouse_id = w1.id
            JOIN catalog.warehouses w2 ON t.dst_warehouse_id = w2.id
            JOIN catalog.cities c1 ON w1.city = c1.name
            JOIN catalog.cities c2 ON w2.city = c2.name
            WHERE t.status = 'planned' AND ti.created_by = %s
            ORDER BY t.id
        """, (user_id,))
        active_transfers = cur.fetchall()

    if not active_transfers:
        render_error("У вас нет созданных позиций в запланированных перемещениях.")
        return

    t_id = choice("Шаг 1: Выберите накладную перемещения (Трансфер):", options=active_transfers)
    if t_id is None: return

    with conn.cursor() as cur:
        cur.execute("""
            SELECT ti.id, p.sku || ' - ' || p.name, ti.quantity, t.src_warehouse_id, ti.product_id
            FROM inventory.transfer_items ti
            JOIN inventory.transfers t ON ti.transfer_id = t.id
            JOIN catalog.products p ON ti.product_id = p.id
            WHERE ti.transfer_id = %s AND ti.created_by = %s AND ti.status = 'planned'
        """, (t_id, user_id))
        items = cur.fetchall()

    if not items:
        render_error("В этой накладной больше нет ваших запланированных позиций.")
        return

    options = [(row[0], f"{row[1]} [В машине: {row[2]} шт.]") for row in items]
    selected_ti_id = choice("Шаг 2: Выберите позицию для удаления/уменьшения:", options=options)
    if selected_ti_id is None: return

    target_item = next(i for i in items if i[0] == selected_ti_id)
    max_qty = target_item[2]
    src_warehouse_id = target_item[3]
    product_id = target_item[4]

    qty_str = prompt(f"Шаг 3: Укажите количество для удаления (макс. {max_qty}): ",
                     validator=QuantityValidator()).strip()
    rem_qty = int(qty_str)

    if rem_qty > max_qty:
        render_error("Ошибка бизнес-логики: Нельзя извлечь больше товара, чем находится в машине!")
        return

    ans = prompt(f"Шаг 4: Подтверждаете извлечение {rem_qty} шт. из машины? (y/n): ", validator=YesNoValidator())
    if not YesNoValidator.is_yes(ans):
        console.print("[yellow]Операция отменена. Состав груза не изменялся.[/yellow]")
        return

    try:
        with conn.transaction():
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT quantity FROM inventory.transfer_items 
                    WHERE id = %s AND status = 'planned' FOR UPDATE
                """, (selected_ti_id,))
                current_ti_row = cur.fetchone()

                if not current_ti_row or current_ti_row[0] < rem_qty:
                    render_error(
                        "[red]Ошибка транзакции: состав груза в машине изменился, пока вы подтверждали удаление![/red]")
                    return

                current_qty = current_ti_row[0]

                cur.execute("""
                    INSERT INTO inventory.stock (warehouse_id, product_id, quantity) VALUES (%s, %s, %s)
                    ON CONFLICT (warehouse_id, product_id) 
                    DO UPDATE SET quantity = inventory.stock.quantity + EXCLUDED.quantity
                """, (src_warehouse_id, product_id, rem_qty))

                if rem_qty == current_qty:
                    cur.execute("DELETE FROM inventory.transfer_items WHERE id = %s", (selected_ti_id,))
                else:
                    cur.execute("UPDATE inventory.transfer_items SET quantity = quantity - %s WHERE id = %s",
                                (rem_qty, selected_ti_id))

        console.print(
            f"[bold green]✓ Операция успешна! {rem_qty} шт. извлечены из машины и вернулись на Склад #{src_warehouse_id}.[/bold green]")

    except Exception as e:
        render_error(f"Критическая ошибка транзакции при удалении: {e}")


@command("list transfers planned all", "вывод всех запланированных перемещений сгруппированных по маршрутам",
         CATEGORY_INVENTORY_MGMT, [ROLE_INVENTORY_MANAGER])
def list_transfers_planned_all() -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.id, c1.name || ' (' || w1.address || ')', c2.name || ' (' || w2.address || ')'
            FROM inventory.transfers t
            JOIN catalog.warehouses w1 ON t.src_warehouse_id = w1.id
            JOIN catalog.warehouses w2 ON t.dst_warehouse_id = w2.id
            JOIN catalog.cities c1 ON w1.city = c1.name
            JOIN catalog.cities c2 ON w2.city = c2.name
            WHERE t.status = 'planned'
            ORDER BY c1.name, c2.name
        """)
        transfers = cur.fetchall()

    if not transfers:
        console.print("[yellow]В системе нет активных запланированных (planned) перемещений между складами.[/yellow]")
        return

    for t_id, src_name, dst_name in transfers:
        console.print(
            f"\n[bold magenta]═══════════════════════════════════════════════════════════════════[/bold magenta]")
        console.print(f"[bold white] Маршрут: {src_name} ➔ {dst_name}[/bold white]  [dim](Трансфер ID: #{t_id})[/dim]")
        console.print(
            f"[bold magenta]═══════════════════════════════════════════════════════════════════[/bold magenta]")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("ID Позиции", justify="right", style="dim")
        table.add_column("Товар (ID / Название)", min_width=25)
        table.add_column("Менеджер (Создатель)", style="yellow")
        table.add_column("Количество", justify="right", style="green")
        table.add_column("Назначение (Заказ)", justify="center")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT ti.id, p.id, p.sku || ' - ' || p.name, u.username, ti.quantity, ti.order_id
                FROM inventory.transfer_items ti
                JOIN catalog.products p ON ti.product_id = p.id
                JOIN auth.users u ON ti.created_by = u.id
                WHERE ti.transfer_id = %s
                ORDER BY ti.id
            """, (t_id,))
            items = cur.fetchall()

        for ti_id, p_id, p_name, manager, qty, o_id in items:
            dest_text = f"[bold green]Заказ #{o_id}[/bold green]" if o_id else "[dim]Прозапас[/dim]"
            table.add_row(str(ti_id), f"[{p_id}] {p_name}", manager, str(qty), dest_text)

        console.print(table)
    console.print("")

    
    
    
    

