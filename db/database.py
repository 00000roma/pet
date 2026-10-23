# db/database.py
from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db.models import Base

DB_PATH = Path(os.getenv("DB_PATH", "data/xray_manager.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)


# ← Включаем foreign keys для SQLite (иначе ON DELETE CASCADE не работает)
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_schema()


def _table_exists(name: str) -> bool:
    return inspect(engine).has_table(name)


def _columns_of(table: str) -> set[str]:
    return {col["name"] for col in inspect(engine).get_columns(table)}


def _add_column(table: str, definition: str) -> None:
    with engine.begin() as conn:
        try:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {definition}"))
        except OperationalError as e:
            # Гонка: другой процесс уже добавил эту колонку — это нормально.
            if "duplicate column name" not in str(e).lower():
                raise


def _migrate_schema() -> None:
    """Достраивает колонки, добавленные в модели уже после создания БД.

    create_all умеет только создавать отсутствующие таблицы, но не
    добавлять новые колонки в существующие. Делаем это вручную и идемпотентно.
    """
    if _table_exists("users"):
        cols = _columns_of("users")
        if "token" not in cols:
            _add_column("users", "token VARCHAR(64)")

    if _table_exists("servers"):
        cols = _columns_of("servers")
        if "network" not in cols:
            _add_column("servers", "network VARCHAR(16) DEFAULT 'xhttp'")
        if "grpc_service_name" not in cols:
            _add_column("servers", "grpc_service_name VARCHAR(64) DEFAULT ''")
        if "xhttp_path" not in cols:
            _add_column("servers", "xhttp_path VARCHAR(64) DEFAULT '/xhttp'")
        if "xhttp_mode" not in cols:
            _add_column("servers", "xhttp_mode VARCHAR(16) DEFAULT 'auto'")
        if "xhttp_host" not in cols:
            _add_column("servers", "xhttp_host VARCHAR(128) DEFAULT ''")
        if "fingerprint" not in cols:
            _add_column("servers", "fingerprint VARCHAR(32) DEFAULT 'chrome'")
        if "managed" not in cols:
            _add_column("servers", "managed BOOLEAN DEFAULT 1")

    if _table_exists("user_servers"):
        cols = _columns_of("user_servers")
        if "uuid" not in cols:
            _add_column("user_servers", "uuid VARCHAR(64)")

    _backfill()


def _backfill() -> None:
    """Заполняет обязательные поля у строк, созданных до миграции."""
    from db.models import User, UserServer

    session = SessionLocal()
    try:
        for user in session.query(User).filter(User.token.is_(None)).all():
            user.token = secrets.token_urlsafe(24)
        for us in session.query(UserServer).filter(UserServer.uuid.is_(None)).all():
            # Связки, созданные до появления per-server UUID (до 13.10), в Xray-конфиге
            # и vless-ссылках использовали ОБЩИЙ user.uuid. Восстанавливаем именно его,
            # а не случайный — иначе новые ссылки не совпадут с уже развёрнутыми
            # на серверах клиентами и VPN сломается.
            owner = session.query(User).filter(User.id == us.user_id).one_or_none()
            us.uuid = owner.uuid if owner else str(uuid.uuid4())
        session.commit()
    finally:
        session.close()


def get_session():
    return SessionLocal()