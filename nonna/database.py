"""Database connection for Nonna.

Reads DATABASE_URL from the environment (or a .env file in the repo root)
and sets up a SQLAlchemy engine and session factory.

Check the connection from the repo root:
    uv run python -m nonna.database
"""

import os
from collections.abc import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

# Load variables from .env into the environment (does nothing if .env is missing)
load_dotenv()


def get_database_url() -> str:
    """Return the database URL, with a clear message if it is not set."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env in the repo root "
            "and check that DATABASE_URL points to your Postgres database."
        )
    return url


# One engine for the whole app. It manages a pool of connections to Postgres.
# pool_pre_ping checks a connection is still alive before using it.
engine: Engine = create_engine(get_database_url(), pool_pre_ping=True)

# Factory for sessions. A session is one unit of work with the database.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Yield a session and always close it afterwards.

    FastAPI endpoints will use this later as a dependency.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_connection() -> None:
    """Connect to the database and print a few basic facts."""
    try:
        with engine.connect() as conn:
            database = conn.execute(text("SELECT current_database()")).scalar_one()
            version = conn.execute(text("SHOW server_version")).scalar_one()
            counterparties = conn.execute(
                text("SELECT count(*) FROM counterparties")
            ).scalar_one()
    except OperationalError as error:
        raise SystemExit(
            "Could not connect to Postgres. Is it running, and is DATABASE_URL correct?\n"
            f"Details: {error.orig}"
        ) from error

    print(f"Connected to database: {database}")
    print(f"Postgres version: {version}")
    print(f"Counterparties in database: {counterparties}")


if __name__ == "__main__":
    check_connection()
