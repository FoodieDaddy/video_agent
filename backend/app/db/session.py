"""Engine/session lifecycle.

The API process and background workers share the same session factory.  Each
background task opens its own short-lived session so a long-running generation
never holds a request transaction open.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.models.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(settings: Settings | None = None) -> Engine:
    global _engine, _session_factory
    settings = settings or get_settings()
    url = settings.database_url

    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # ``sqlite:///relative`` would resolve against CWD; make it absolute.
        if not url.startswith("sqlite:////") and ":///" in url:
            raw_path = url.split(":///", 1)[1]
            if raw_path and raw_path != ":memory:":
                path = Path(raw_path)
                if not path.is_absolute():
                    path = (settings.data_dir / path.name).resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                url = f"sqlite:///{path.as_posix()}"

    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, **kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def init_schema() -> None:
    # Import models so every table is registered on the metadata.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def reset_engine() -> None:
    """Testing helper: drop the engine so the next call rebuilds from settings."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
