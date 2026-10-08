"""Database engine, sessions and the declarative base."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """Every datetime is stored as UTC and read back as aware UTC.

    SQLite keeps no zone: a Tehran-local 18:30 was stored as "18:30" and
    read back as 18:30 UTC. Converting on the way in fixes that on every
    backend; a naive datetime is refused, since its zone is unknown.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: give it a timezone")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime()}


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


_engine = None
_session_factory: sessionmaker[Session] | None = None


def engine():
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, **kwargs)
        _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def configure(url: str) -> None:
    """Point the module at another database (tests)."""
    global _engine, _session_factory
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    _engine = create_engine(url, **kwargs)
    _session_factory = sessionmaker(_engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed on success."""
    with session_scope() as session:
        yield session
