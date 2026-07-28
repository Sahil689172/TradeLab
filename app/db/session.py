"""SQLAlchemy engine and session management."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.base import Base

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory for a SQLite file database if needed."""
    if not database_url.startswith("sqlite:///"):
        return

    # sqlite:///./data/tradlab.db  ->  ./data/tradlab.db
    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path in {":memory:", ""} or raw_path.startswith("file:"):
        return

    db_path = Path(raw_path)
    if db_path.parent and str(db_path.parent) not in {".", ""}:
        db_path.parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy engine from application settings.

    Args:
        settings: Optional settings override (defaults to global settings).

    Returns:
        Configured SQLAlchemy ``Engine``.
    """
    cfg = settings or get_settings()
    _ensure_sqlite_directory(cfg.database_url)

    connect_args: dict[str, object] = {}
    if cfg.is_sqlite:
        # Required for SQLite used across FastAPI request threads.
        connect_args["check_same_thread"] = False

    engine = create_engine(
        cfg.database_url,
        connect_args=connect_args,
    )
    logger.debug("SQLAlchemy engine created for %s", cfg.database_url)
    return engine


def init_db(settings: Settings | None = None) -> Engine:
    """Initialize the global engine, session factory, and schema.

    Creates tables for all models registered on ``Base``. Phase A1 has no
    business models, so this primarily validates connectivity and prepares
    the schema hook for future modules.

    Args:
        settings: Optional settings override.

    Returns:
        The initialized SQLAlchemy engine.
    """
    global _engine, _SessionLocal

    cfg = settings or get_settings()
    _engine = create_db_engine(cfg)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    Base.metadata.create_all(bind=_engine)
    logger.info("Database initialized successfully")
    return _engine


def get_engine() -> Engine:
    """Return the global engine, initializing it if necessary."""
    global _engine
    if _engine is None:
        init_db()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the global session factory, initializing DB if necessary."""
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    Yields:
        An open SQLAlchemy ``Session``, closed after the request.
    """
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def check_database_connection(engine: Engine | None = None) -> bool:
    """Return True if a simple connectivity query succeeds.

    Args:
        engine: Optional engine; uses the global engine when omitted.

    Returns:
        ``True`` when the database responds to ``SELECT 1``.
    """
    eng = engine or get_engine()
    try:
        with eng.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed")
        return False


def reset_db_state() -> None:
    """Dispose and clear global engine/session state (for tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
