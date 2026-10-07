# db/models.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    host: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str] = mapped_column(String(32), default="root")
    ssh_key_path: Mapped[str] = mapped_column(String(512), nullable=False)

    xray_port: Mapped[int] = mapped_column(Integer, default=443)
    reality_dest: Mapped[str] = mapped_column(String(128), default="")
    reality_server_names: Mapped[str] = mapped_column(Text, default="[]")
    reality_private_key: Mapped[str] = mapped_column(Text, default="")
    reality_public_key: Mapped[str] = mapped_column(Text, default="")
    reality_short_ids: Mapped[str] = mapped_column(Text, default="[]")

    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserServer(Base):
    __tablename__ = "user_servers"
    __table_args__ = (UniqueConstraint("user_id", "server_id", name="uq_user_server"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    flow: Mapped[str] = mapped_column(String(32), default="xtls-rprx-vision")