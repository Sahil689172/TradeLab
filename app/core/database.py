"""SQLAlchemy engine, session management, and database initialization."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy ORM models."""

    pass


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory for a SQLite file database if needed."""
    if not database_url.startswith("sqlite:///"):
        return

    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path in {":memory:", ""} or raw_path.startswith("file:"):
        return

    db_path = Path(raw_path)
    if db_path.parent and str(db_path.parent) not in {".", ""}:
        db_path.parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy engine from application settings.

    Uses ``metadata_database_url`` when initializing market metadata tables,
    falling back to ``database_url`` for general app connectivity checks.
    """
    cfg = settings or get_settings()
    db_url = cfg.metadata_database_url if cfg.metadata_database_url else cfg.database_url
    _ensure_sqlite_directory(db_url)

    connect_args: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(db_url, connect_args=connect_args)
    logger.debug("SQLAlchemy engine created for %s", db_url)
    return engine


def init_db(settings: Settings | None = None) -> Engine:
    """Initialize engine, session factory, and create all ORM tables.

    Imports market-data models so they register on ``Base.metadata`` before
    ``create_all`` runs.
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

    # Register ORM models before create_all.
    import app.market_data.models  # noqa: F401

    Base.metadata.create_all(bind=_engine)
    logger.info("Metadata database initialized at %s", cfg.metadata_db_path)
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
    """FastAPI dependency that yields a database session."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def check_database_connection(engine: Engine | None = None) -> bool:
    """Return True if a simple connectivity query succeeds."""
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
