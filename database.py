"""
database.py
============
Single source of all DB connectivity for the KOL Distributor Toys
Inventory Control Tower.

Every service, router, and scheduler gets its DB session from this module.

Configuration is loaded from environment variables:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

Edge cases handled:
    - Any env var is None or empty → RuntimeError listing missing vars
    - DB_PORT is not castable to int → ValueError
    - Session close fails → logged as warning, never raised

Assumptions NOT made:
    - Not assuming env vars are always present
    - Not assuming DB_PORT is always numeric
    - Not assuming session.close() always succeeds
"""

import logging
import os
from typing import Generator
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def validate_env_vars() -> dict[str, str]:
    """
    Validate that all required database environment variables are present
    and non-empty.

    Returns:
        Dict mapping variable name → value for all required vars.

    Raises:
        RuntimeError: If any required variable is missing or empty,
                      listing exactly which ones.
        ValueError: If DB_PORT cannot be cast to int.
    """
    values: dict[str, str] = {}
    missing: list[str] = []

    for var in _REQUIRED_ENV_VARS:
        val = os.getenv(var)
        if val is None or val.strip() == "":
            missing.append(var)
        else:
            values[var] = val.strip()

    if missing:
        raise RuntimeError(
            f"Missing or empty required database environment variables: "
            f"{', '.join(missing)}. "
            f"Set them before starting the application."
        )

    # Validate DB_PORT is a valid integer
    try:
        int(values["DB_PORT"])
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"DB_PORT must be a valid integer, got '{values['DB_PORT']}'."
        ) from exc

    return values


# ---------------------------------------------------------------------------
# Engine & session factory setup
# ---------------------------------------------------------------------------

# Validate at import time — fail fast if config is wrong
_env = validate_env_vars()

_DATABASE_URL = (
    f"mysql+pymysql://{_env['DB_USER']}:{_env['DB_PASSWORD']}"
    f"@{_env['DB_HOST']}:{_env['DB_PORT']}/{_env['DB_NAME']}"
)

# Never log the URL — it contains the password
logger.info(
    "Database engine configured for %s:%s/%s",
    _env["DB_HOST"],
    _env["DB_PORT"],
    _env["DB_NAME"],
)

engine = create_engine(
    _DATABASE_URL,
    pool_pre_ping=True,     # Auto-reconnect on stale connections
    pool_recycle=3600,       # Recycle connections every hour
    echo=False,              # Never log raw SQL in production
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


# ---------------------------------------------------------------------------
# Declarative base for ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models in this project."""
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a SQLAlchemy database session.

    Yields:
        A SessionLocal instance bound to the configured engine.

    Usage:
        @app.get("/example")
        def example(db: Session = Depends(get_db)):
            ...

    The session is always closed in the finally block, even if the
    request handler raises an exception.  If session.close() itself
    fails, the error is logged as a warning but never re-raised —
    the original exception (if any) must propagate cleanly.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception as exc:
            logger.warning(
                "Failed to close DB session (non-fatal): %s", exc
            )
