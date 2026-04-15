import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./geo_search.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

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
        },
        "screening_results": {
            "description": "TEXT",
            "keyword_matched": "BOOLEAN DEFAULT 1",
        },
    }

    for table, columns in required_columns.items():
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}
        for column, ddl in columns.items():
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
