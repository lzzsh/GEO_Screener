import os
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./geo_search.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30} if IS_SQLITE else {},
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

if IS_SQLITE:
    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        if ":memory:" not in DATABASE_URL:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        import backend.models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
        await _run_sqlite_migrations(conn)


async def _run_sqlite_migrations(conn):
    if not DATABASE_URL.startswith("sqlite"):
        return

    required_columns = {
        "screening_tasks": {
            "search_query": "TEXT",
            "candidate_count": "INTEGER DEFAULT 0",
            "included_count": "INTEGER DEFAULT 0",
            "excluded_count": "INTEGER DEFAULT 0",
            "uncertain_count": "INTEGER DEFAULT 0",
            "label_schema": "TEXT",
        },
        "screening_results": {
            "description": "TEXT",
            "keyword_matched": "BOOLEAN DEFAULT 1",
            "gse_type": "VARCHAR(256)",
            "pubdate": "VARCHAR(32)",
            "update_date": "VARCHAR(32)",
            "has_raw_data": "BOOLEAN DEFAULT 0",
            "n_samples": "INTEGER DEFAULT 0",
        },
    }

    for table, columns in required_columns.items():
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}
        if not existing:
            continue
        for column, ddl in columns.items():
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
