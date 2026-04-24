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

    await _migrate_llm_configs(conn)
    await _deduplicate_geo_samples(conn)


async def _deduplicate_geo_samples(conn):
    if not DATABASE_URL.startswith("sqlite"):
        return
    result = await conn.execute(text("PRAGMA table_info(geo_samples)"))
    if not result.fetchall():
        return

    # Find duplicates: for each (result_id, gsm_id) group keep the row with the
    # most labels (or lowest id on a tie) and re-point any labels on the others.
    dupes = (await conn.execute(text("""
        SELECT result_id, gsm_id
        FROM geo_samples
        GROUP BY result_id, gsm_id
        HAVING COUNT(*) > 1
    """))).fetchall()

    for result_id, gsm_id in dupes:
        rows = (await conn.execute(text(
            "SELECT id FROM geo_samples WHERE result_id=:r AND gsm_id=:g ORDER BY id"
        ), {"r": result_id, "g": gsm_id})).fetchall()
        ids = [r[0] for r in rows]

        # Pick the survivor: prefer the one that already has labels
        label_counts = []
        for sid in ids:
            cnt = (await conn.execute(
                text("SELECT COUNT(*) FROM gsm_labels WHERE sample_id=:s"), {"s": sid}
            )).scalar()
            label_counts.append((cnt, sid))
        label_counts.sort(key=lambda x: (-x[0], x[1]))
        survivor = label_counts[0][1]
        losers = [sid for _, sid in label_counts[1:]]

        for loser in losers:
            # Move labels that don't conflict with survivor's existing keys
            existing_keys = {r[0] for r in (await conn.execute(
                text("SELECT key FROM gsm_labels WHERE sample_id=:s"), {"s": survivor}
            )).fetchall()}
            loser_labels = (await conn.execute(
                text("SELECT key, value, source FROM gsm_labels WHERE sample_id=:s"), {"s": loser}
            )).fetchall()
            for key, value, source in loser_labels:
                if key not in existing_keys:
                    await conn.execute(text(
                        "INSERT INTO gsm_labels(sample_id, key, value, source) VALUES(:s,:k,:v,:src)"
                    ), {"s": survivor, "k": key, "v": value, "src": source})
            await conn.execute(text("DELETE FROM gsm_labels WHERE sample_id=:s"), {"s": loser})
            await conn.execute(text("DELETE FROM geo_samples WHERE id=:s"), {"s": loser})

    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_samples_result_gsm
        ON geo_samples(result_id, gsm_id)
    """))


async def _migrate_llm_configs(conn):
    # Check if old schema (unique on owner_id alone, no is_active column)
    result = await conn.execute(text("PRAGMA table_info(llm_configs)"))
    cols = {row[1] for row in result.fetchall()}
    if not cols:
        return  # table doesn't exist yet, create_all will handle it

    if "is_active" in cols:
        # Already migrated; just ensure api_key column is wide enough (SQLite ignores size, no-op)
        return

    # Old schema: rename, recreate, migrate data
    await conn.execute(text("ALTER TABLE llm_configs RENAME TO llm_configs_old"))
    await conn.execute(text("""
        CREATE TABLE llm_configs (
            id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL REFERENCES users(id),
            provider VARCHAR(32) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 0,
            api_key VARCHAR(512),
            base_url VARCHAR(256),
            model VARCHAR(128),
            temperature FLOAT DEFAULT 0.1,
            UNIQUE (owner_id, provider)
        )
    """))
    await conn.execute(text("""
        INSERT INTO llm_configs (owner_id, provider, is_active, api_key, base_url, model, temperature)
        SELECT owner_id, provider, 1, api_key, base_url, model, temperature
        FROM llm_configs_old
    """))
    await conn.execute(text("DROP TABLE llm_configs_old"))
