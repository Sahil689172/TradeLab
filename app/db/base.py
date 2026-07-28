"""SQLAlchemy declarative base for ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models.

    Phase A1 defines no business models. Future modules will inherit from
    this base when introducing domain tables.
    """

    pass
