from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from rich.table import Table

from console import console, render_error
from db import get_conn
from validators import NonEmptyValidator, YesNoValidator
from commands import command

CATEGORY_ROUTES = "Управление маршрутами"
ROLE_INVENTORY_MANAGER = "inventory_manager"

class RouteValidator(NonEmptyValidator):
    def validate(self, document):
        super().validate(document)
        try:
            val = float(document.text)
            if val < 0: raise ValueError
        except ValueError:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Значение должно быть числовым и больше или равно 0.")


class IntervalValidator(NonEmptyValidator):
    def validate(self, document):
        super().validate(document)
        text = document.text.strip()
        if ":" not in text:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Введите время в формате ММ:СС (например, 05:30)")
        try:
            parts = text.split(":")
            minutes, seconds = int(parts[0]), int(parts[1])
            if minutes < 0 or seconds < 0 or seconds >= 60:
                raise ValueError
        except ValueError:
            from prompt_toolkit.validation import ValidationError
            raise ValidationError(message="Некорректный формат. Секунды должны быть от 00 до 59.")


def _db_fetch_cities(mode: str, parent_id: int = None) -> list:
    conn = get_conn()
    with conn.cursor() as cur:
        if mode == "from":
            cur.execute("""
                SELECT DISTINCT c.id, c.name FROM catalog.routes r 
                JOIN catalog.cities c ON r.from_city_id = c.id ORDER BY c.name
            """)
        elif mode == "to_filtered":
            cur.execute("""
                SELECT DISTINCT c.id, c.name FROM catalog.routes r 
                JOIN catalog.cities c ON r.to_city_id = c.id 
                WHERE r.from_city_id = %s ORDER BY c.name
            """, (parent_id,))
        else:
            cur.execute("SELECT id, name FROM catalog.cities ORDER BY name")
        return cur.fetchall()


@command("list routes", "список всех логистических маршрутов", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def list_routes() -> None:
    conn = get_conn()
    table = Table(title="Логистические маршруты между городами", show_header=True, header_style="bold cyan")
    table.add_column("Откуда (Город отправки)", style="green", min_width=20)
    table.add_column("Куда (Город приемки)", style="yellow", min_width=20)
    table.add_column("Время доставки", style="magenta", justify="right", width=22)
    table.add_column("Минимальная сумма (порог)", style="green", justify="right", width=25)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT c1.name, c2.name, r.duration, r.total_threshold 
            FROM catalog.routes r
            JOIN catalog.cities c1 ON r.from_city_id = c1.id
            JOIN catalog.cities c2 ON r.to_city_id = c2.id
            ORDER BY c1.name, c2.name
        """)
        routes = cur.fetchall()

    for f_city, t_city, duration, threshold in routes:
        # Форматируем timedelta в ММ:СС для вывода
        total_seconds = int(duration.total_seconds())
        mins = total_seconds // 60
        secs = total_seconds % 60
        table.add_row(f_city, t_city, f"{mins:02d}:{secs:02d}", f"{threshold:.2f} руб.")
    console.print(table)


@command("add route", "создать новый маршрут перемещения", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def add_route() -> None:
    conn = get_conn()

    # --- ЗВЕЗДОЧКА 1: Выбор города А (from) одним SQL-запросом ---
    # Показываем только те города, из которых проложены маршруты НЕ во все остальные города
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.name 
            FROM catalog.cities c
            WHERE EXISTS (
                -- Ищем хотя бы один город Б, пары с которым еще нет в таблице routes
                SELECT 1 FROM catalog.cities c2
                WHERE c2.id != c.id 
                  AND NOT EXISTS (
                      SELECT 1 FROM catalog.routes r 
                      WHERE r.from_city_id = c.id AND r.to_city_id = c2.id
                  )
            )
            ORDER BY c.name
        """)
        allowed_sources = cur.fetchall()

    if not allowed_sources:
        render_error("Все возможные логистические маршруты между городами уже полностью сконфигурированы!")
        return

    from_options = [(c_id, name) for c_id, name in allowed_sources]
    from_id = choice(message="Выберите город склада отправки (Пункт А):", options=from_options)
    if from_id is None: return


    # --- ЗВЕЗДОЧКА 2: Выбор города Б (to) одним SQL-запросом ---
    # Выбираем только те города, пары с которыми для выбранного from_id еще нет в базе
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.name 
            FROM catalog.cities c
            WHERE c.id != %s 
              AND NOT EXISTS (
                  SELECT 1 FROM catalog.routes r 
                  WHERE r.from_city_id = %s AND r.to_city_id = c.id
              )
            ORDER BY c.name
        """, (from_id, from_id))
        allowed_destinations = cur.fetchall()

    # Из-за первой проверки этот блок никогда не сработает, но оставим для надежности
    if not allowed_destinations:
        render_error("Для выбранного города отправки уже настроены все возможные маршруты назначения.")
        return

    to_options = [(c_id, name) for c_id, name in allowed_destinations]
    to_id = choice(message="Выберите город склада приемки (Пункт Б):", options=to_options)
    if to_id is None: return


    # --- Ввод параметров и сохранение ---
    duration_str = prompt("Укажите время доставки (формат ММ:СС, например 05:30): ", validator=IntervalValidator()).strip()
    threshold_str = prompt("Укажите минимальную сумму (total_threshold): ", validator=RouteValidator()).strip()

    conn.execute(
        "INSERT INTO catalog.routes (from_city_id, to_city_id, duration, total_threshold) VALUES (%s, %s, %s::interval, %s)",
        (from_id, to_id, f"00:{duration_str}", float(threshold_str))
    )
    console.print("[green]Логистический маршрут успешно зафиксирован в системе.[/green]")



@command("show route", "просмотр параметров конкретного маршрута", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def show_route() -> None:
    conn = get_conn()
    from_cities = _db_fetch_cities("from")
    if not from_cities:
        render_error("В базе данных еще нет ни одного настроенного маршрута.")
        return

    from_id = choice(message="Выберите город отправки:", options=[(c_id, name) for c_id, name in from_cities])
    if from_id is None: return

    to_cities = _db_fetch_cities("to_filtered", from_id)
    to_id = choice(message="Выберите город接收ки:", options=[(c_id, name) for c_id, name in to_cities])
    if to_id is None: return

    with conn.cursor() as cur:
        cur.execute("""
            SELECT c1.name, c2.name, r.duration, r.total_threshold 
            FROM catalog.routes r
            JOIN catalog.cities c1 ON r.from_city_id = c1.id
            JOIN catalog.cities c2 ON r.to_city_id = c2.id
            WHERE r.from_city_id = %s AND r.to_city_id = %s
        """, (from_id, to_id))
        route = cur.fetchone()

    total_seconds = int(route[2].total_seconds())
    mins = total_seconds // 60
    secs = total_seconds % 60

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Параметр", style="bold cyan", width=25)
    table.add_column("Значение", style="white")
    table.add_row("Город отправки (From)", route[0])
    table.add_row("Город приемки (To)", route[1])
    table.add_row("Время доставки (Duration)", f"{mins:02d}:{secs:02d}")
    table.add_row("Порог стоимости (Threshold)", f"{route[3]:,.2f} руб.", style="bold green")
    console.print(table)


@command("edit route", "изменить параметры существующего маршрута", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def edit_route() -> None:
    conn = get_conn()
    from_cities = _db_fetch_cities("from")
    if not from_cities: return

    from_id = choice(message="Выберите город отправки:", options=[(c_id, name) for c_id, name in from_cities])
    if from_id is None: return

    to_cities = _db_fetch_cities("to_filtered", from_id)
    to_id = choice(message="Выберите город приемки:", options=[(c_id, name) for c_id, name in to_cities])
    if to_id is None: return

    with conn.cursor() as cur:
        cur.execute("SELECT duration, total_threshold FROM catalog.routes WHERE from_city_id = %s AND to_city_id = %s", (from_id, to_id))
        row = cur.fetchone()

    total_seconds = int(row[0].total_seconds())
    current_interval = f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"

    new_dur = prompt("Время доставки (ММ:СС): ", default=current_interval, validator=IntervalValidator()).strip()
    new_thresh = prompt("Минимальная сумма (порог): ", default=str(row[1]), validator=RouteValidator()).strip()

    conn.execute(
        "UPDATE catalog.routes SET duration = %s::interval, total_threshold = %s WHERE from_city_id = %s AND to_city_id = %s",
        (f"00:{new_dur}", float(new_thresh), from_id, to_id)
    )
    console.print("[green]Параметры маршрута перемещения успешно изменены.[/green]")


@command("delete route", "удалить логистический маршрут", CATEGORY_ROUTES, [ROLE_INVENTORY_MANAGER])
def delete_route() -> None:
    conn = get_conn()
    from_cities = _db_fetch_cities("from")
    if not from_cities: return

    from_id = choice(message="Выберите город отправки:", options=[(c_id, name) for c_id, name in from_cities])
    if from_id is None: return

    to_cities = _db_fetch_cities("to_filtered", from_id)
    to_id = choice(message="Выберите город приемки:", options=[(c_id, name) for c_id, name in to_cities])
    if to_id is None: return

    ans = prompt("Вы уверены, что хотите удалить данный маршрут? (y/n, д/н): ", validator=YesNoValidator())
    if YesNoValidator.is_yes(ans):
        conn.execute("DELETE FROM catalog.routes WHERE from_city_id = %s AND to_city_id = %s", (from_id, to_id))
        console.print("[green]Маршрут успешно удален из системы.[/green]")

