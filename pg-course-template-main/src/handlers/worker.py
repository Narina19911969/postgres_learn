from datetime import datetime, timedelta
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from rich.table import Table

from console import console, render_error
from db import get_conn
from auth import auth_user
from validators import YesNoValidator
from commands import command

CATEGORY_WORKER = "Складские операции (Кладовщик)"
ROLE_WORKER = "worker"


def _get_worker_wh(cur, user_id: int) -> int:
    cur.execute("SELECT warehouse_id FROM auth.users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if not row or row is None:
        return None
    return int(row[0])  # Гарантированный чистый int


@command("list transfers shipping", "список доступных трансферов", CATEGORY_WORKER, [ROLE_WORKER])
def list_transfers_shipping() -> None:
    conn = get_conn()
    user_id = auth_user().id

    with conn.cursor() as cur:
        user_wh_id = _get_worker_wh(cur, user_id)
        if not user_wh_id:
            render_error("За вашим пользователем не закреплен склад.")
            return

        cur.execute("""
            SELECT t.id, t.status, c1.name || ' -> ' || c2.name
            FROM inventory.transfers t
            JOIN catalog.warehouses w1 ON t.src_warehouse_id = w1.id
            JOIN catalog.warehouses w2 ON t.dst_warehouse_id = w2.id
            JOIN catalog.cities c1 ON w1.city = c1.name
            JOIN catalog.cities c2 ON w2.city = c2.name
            WHERE (t.src_warehouse_id = %s AND t.status = 'shipping')
               OR (t.dst_warehouse_id = %s AND t.status IN ('in_transit', 'arrived'))
            ORDER BY t.id
        """, (user_wh_id, user_wh_id))
        transfers = cur.fetchall()

    table = Table(title="📋 Доступные накладные перемещений", show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="center")
    table.add_column("Маршрут")
    table.add_column("Статус", style="yellow")

    for t in transfers:
        t_id = int(t[0])
        status = str(t[1])
        route = str(t[2])
        table.add_row(str(t_id), route, status)
    console.print(table)


@command("ship transfer", "попозиционная сборка и отправка трансфера в путь", CATEGORY_WORKER, [ROLE_WORKER])
def ship_transfer(transfer_id: str) -> None:
    conn = get_conn()
    t_id = int(transfer_id)
    user_id = auth_user().id

    with conn.cursor() as cur:
        user_wh_id = _get_worker_wh(cur, user_id)
        cur.execute("SELECT status, src_warehouse_id, dst_warehouse_id FROM inventory.transfers WHERE id = %s", (t_id,))
        t_row = cur.fetchone()

    if not t_row or t_row is None:
        render_error(f"Трансфер #{t_id} не найден.")
        return

    status = str(t_row[0])
    src_wh = int(t_row[1])
    dst_wh = int(t_row[2])

    if src_wh != user_wh_id:
        render_error("Вы можете отгружать перемещения только со своего склада!")
        return

    if status != 'shipping':
        render_error(f"Статус трансфера: '{status}', а для сборки ожидался 'shipping'.")
        return

    while True:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ti.id, p.sku || ' - ' || p.name, ti.quantity, ti.status 
                FROM inventory.transfer_items ti
                JOIN catalog.products p ON ti.product_id = p.id
                WHERE ti.transfer_id = %s
                ORDER BY ti.id
            """, (t_id,))
            items = cur.fetchall()

        planned = [i for i in items if str(i[3]) == 'planned']
        if not planned:
            console.print("[green]Все позиции успешно отсканированы и переведены в 'shipped'.[/green]")
            break

        options = []
        for i in items:
            ti_id = int(i[0])
            prod = str(i[1])
            qty = int(i[2])
            st = str(i[3])
            lbl = "✓ СЧИТАНО" if st == 'shipped' else "ОЖИДАЕТ"
            options.append((ti_id, f"{prod} ({qty} шт.) [{lbl}]"))
        options.append((None, "--> Прервать сборку и выйти <--"))

        sel_id = choice("Сканируйте штрихкод упаковки товара:", options=options)
        if sel_id is None:
            return

        target = next(i for i in items if int(i[0]) == sel_id)
        if str(target[3]) == 'shipped':
            console.print("[yellow]Этот товар уже отгружен.[/yellow]")
            continue

        ans = prompt("Подтвердить отгрузку позиции в машину? (y/n): ", validator=YesNoValidator())
        if YesNoValidator.is_yes(ans):
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("UPDATE inventory.transfer_items SET status = 'shipped' WHERE id = %s", (sel_id,))
            console.print("[green]✓ Товар погружен.[/green]")

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.duration 
                FROM inventory.routes r
                WHERE r.from_city_id = (
                    SELECT c.id FROM catalog.warehouses w
                    JOIN catalog.cities c ON w.city = c.name
                    WHERE w.id = %s
                ) AND r.to_city_id = (
                    SELECT c.id FROM catalog.warehouses w
                    JOIN catalog.cities c ON w.city = c.name
                    WHERE w.id = %s
                )
            """, (src_wh, dst_wh))
            r_row = cur.fetchone()

            if r_row and r_row[0] is not None:
                val = r_row[0]
                if hasattr(val, "total_seconds"):
                    dur = int(val.total_seconds())
                else:
                    dur = int(val)
            else:
                dur = 3600

            arr_time = datetime.now() + timedelta(seconds=dur)
            cur.execute("UPDATE inventory.transfers SET status = 'in_transit', arriving_at = %s WHERE id = %s",
                        (arr_time, t_id))

    console.print(
        f"[bold green]✓ Трансфер #{t_id} отправлен! Время прибытия: {arr_time.strftime('%H:%M:%S')}[/bold green]")


@command("check transfers", "фиксация прибытия машин из транзита на склад приемки", CATEGORY_WORKER, [ROLE_WORKER])
def check_transfers() -> None:
    conn = get_conn()
    user_id = auth_user().id
    now = datetime.now()

    with conn.transaction():
        with conn.cursor() as cur:
            user_wh_id = _get_worker_wh(cur, user_id)
            if not user_wh_id:
                render_error("За вашим пользователем не закреплен склад.")
                return

            cur.execute("""
                SELECT id, arriving_at FROM inventory.transfers 
                WHERE dst_warehouse_id = %s AND status = 'in_transit' 
                FOR UPDATE
            """, (user_wh_id,))
            cars = cur.fetchall()

            arrived_count = 0
            for car in cars:
                c_id = int(car[0])
                arr_at = car[1]

                if arr_at and now >= arr_at:
                    cur.execute("UPDATE inventory.transfers SET status = 'arrived' WHERE id = %s", (c_id,))
                    console.print(
                        f"[green]🚚 Машина (Трансфер #{c_id}) зафиксирована на КПП. Статус изменен на 'arrived'.[/green]")
                    arrived_count += 1

            if arrived_count == 0 and cars:
                console.print("[yellow]Все ожидаемые машины еще находятся в пути согласно времени маршрута.[/yellow]")
            elif not cars:
                console.print("[yellow]В пути к вашему складу нет активных перемещений товаров.[/yellow]")


@command("receive transfer", "попозиционная разгрузка и оприходование товаров из прибывшей машины", CATEGORY_WORKER,
         [ROLE_WORKER])
def receive_transfer(transfer_id: str) -> None:
    conn = get_conn()
    t_id = int(transfer_id)
    user_id = auth_user().id

    with conn.cursor() as cur:
        user_wh_id = _get_worker_wh(cur, user_id)
        cur.execute("SELECT status, dst_warehouse_id FROM inventory.transfers WHERE id = %s", (t_id,))
        t_row = cur.fetchone()

    if not t_row or t_row is None:
        render_error(f"Трансфер #{t_id} не найден.")
        return

    status = str(t_row[0])
    dst_wh = int(t_row[1])

    if dst_wh != user_wh_id:
        render_error("Вы можете разгружать машины только на своем целевом складе!")
        return

    if status != 'arrived':
        render_error(f"Разгрузка невозможна. Текущий статус перемещения: '{status}', ожидался 'arrived'.")
        return

    while True:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ti.id, p.sku || ' - ' || p.name, ti.quantity, ti.status, ti.order_id, ti.product_id
                FROM inventory.transfer_items ti
                JOIN catalog.products p ON ti.product_id = p.id
                WHERE ti.transfer_id = %s
                ORDER BY ti.id
            """, (t_id,))
            items = cur.fetchall()

        shipped = [i for i in items if str(i[3]) == 'shipped']
        if not shipped:
            console.print("[green]Все товары успешно выгружены из кузова и оприходованы.[/green]")
            break

        options = []
        for i in items:
            ti_id = int(i[0])
            prod = str(i[1])
            qty = int(i[2])
            st = str(i[3])
            o_id = int(i[4]) if i[4] is not None else None
            lbl = f"Заказ #{o_id}" if o_id else "Свободный Сток"
            chk = "✓ ПРИНЯТ" if st == 'received' else "В КУЗОВЕ"
            options.append((ti_id, f"{prod} ({qty} шт.) Назначение: {lbl} [{chk}]"))
        options.append((None, "--> Приостановить разгрузку машины <--"))

        sel_id = choice("Сканируйте штрихкод принимаемой упаковки:", options=options)
        if sel_id is None:
            return

        target = next(i for i in items if int(i[0]) == sel_id)
        if str(target[3]) == 'received':
            console.print("[yellow]Этот товар уже оприходован на баланс склада.[/yellow]")
            continue

        p_id = int(target[5])
        qty = int(target[2])
        o_id = int(target[4]) if target[4] is not None else None

        ans = prompt("Разгрузить и зачислить позицию на баланс? (y/n): ", validator=YesNoValidator())
        if YesNoValidator.is_yes(ans):
            with conn.transaction():
                with conn.cursor() as cur:
                    if o_id:
                        cur.execute("""
                            INSERT INTO inventory.order_reserves (order_id, warehouse_id, product_id, quantity)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (order_id, product_id) 
                            DO UPDATE SET quantity = inventory.order_reserves.quantity + EXCLUDED.quantity
                        """, (o_id, user_wh_id, p_id, qty))
                        console.print(f"[green]✓ Товар зачислен в РЕЗЕРВ под целевой Заказ #{o_id}.[/green]")
                    else:
                        cur.execute("""
                            INSERT INTO inventory.stock (warehouse_id, product_id, quantity)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (warehouse_id, product_id) 
                            DO UPDATE SET quantity = inventory.stock.quantity + EXCLUDED.quantity
                        """, (user_wh_id, p_id, qty))
                        console.print("[green]✓ Товар отправлен на полки в свободный сток.[/green]")

                    cur.execute("UPDATE inventory.transfer_items SET status = 'received' WHERE id = %s", (sel_id,))

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE inventory.transfers SET status = 'received', arriving_at = NOW() WHERE id = %s", (t_id,))
    console.print(f"[bold green]✓ Трансфер #{t_id} успешно переведен в финальный статус 'received'.[/bold green]")


@command("ship delivery", "попозиционная отгрузка собранного заказа покупателю", CATEGORY_WORKER, [ROLE_WORKER])
def ship_delivery(order_id: str) -> None:
    conn = get_conn()
    o_id = int(order_id)
    user_id = auth_user().id

    with conn.cursor() as cur:
        user_wh_id = _get_worker_wh(cur, user_id)
        cur.execute("SELECT warehouse_id FROM inventory.worker_orders_view WHERE order_id = %s", (o_id,))
        o_row = cur.fetchone()

    if not o_row or o_row is None:
        render_error(f"Заказ #{o_id} не найден.")
        return

    wh_id = int(o_row[0])
    if wh_id != user_wh_id:
        render_error("Этот заказ собран и должен отгружаться с другого склада!")
        return

    while True:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.product_id, p.sku || ' - ' || p.name, r.quantity 
                FROM inventory.order_reserves r
                JOIN catalog.products p ON r.product_id = p.id
                WHERE r.order_id = %s AND r.warehouse_id = %s
                ORDER BY r.product_id
            """, (o_id, user_wh_id))
            reserves = cur.fetchall()

        if not reserves:
            console.print(
                "[green]All reserved items for the order have been scanned and shipped to the courier.[/green]")
            break

        options = []
        for r in reserves:
            p_id = int(r[0])
            prod = str(r[1])
            qty = int(r[2])
            options.append((p_id, f"{prod} ({qty} шт.) [В РЕЗЕРВЕ / ОЖИДАЕТ ОТГРУЗКИ]"))
        options.append((None, "--> Прервать отгрузку доставки <--"))

        sel_p_id = choice("Сканируйте штрихкод товара для отправки покупателю:", options=options)
        if sel_p_id is None:
            return

        ans = prompt("Подтвердить отгрузку позиции со склада курьеру? (y/n): ", validator=YesNoValidator())
        if YesNoValidator.is_yes(ans):
            with conn.transaction():
                with conn.cursor() as cur:
                    # Удаляем (списываем) позицию из резерва, так как товар покидает склад навсегда
                    cur.execute("""
                        DELETE FROM inventory.order_reserves 
                        WHERE order_id = %s AND warehouse_id = %s AND product_id = %s
                    """, (o_id, user_wh_id, sel_p_id))
            console.print("[green]✓ Позиция успешно переведена в статус 'shipped' и загружена в машину.[/green]")

    console.print(
        f"[bold green]✓ Все позиции заказа #{o_id} успешно попозиционно отгружены кладовщиком со склада.[/bold green]")
