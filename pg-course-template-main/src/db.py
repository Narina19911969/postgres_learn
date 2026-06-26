from typing import Final

import psycopg
from psycopg import Connection
import os

DB_NAME: Final[str] = os.getenv("DB_NAME", "inventorydb")
DB_USER: Final[str] = os.getenv("DB_USER", "app_user")
DB_PASSWORD: Final[str] = os.getenv("DB_PASSWORD", "123")
DB_HOST: Final[str] = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT: Final[int] = int(os.getenv("DB_PORT", "5432"))

_CONN: Connection | None = None


def connect() -> None:
    global _CONN
    _CONN = psycopg.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        autocommit=True,
    )


def close() -> None:
    if _CONN is not None:
        _CONN.close()


def get_conn() -> Connection:
    if _CONN is None:
        raise RuntimeError("Database connection has not been established")
    return _CONN
