from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_lightweight_migrations()


def _ensure_lightweight_migrations() -> None:
    inspector = inspect(engine)
    if "subtitle_segments" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("subtitle_segments")}
    if "alignment_json" in columns:
        return

    dialect = engine.dialect.name
    column_type = "JSON" if dialect in {"mysql", "mariadb", "postgresql"} else "TEXT"
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE subtitle_segments ADD COLUMN alignment_json {column_type} NULL"))
