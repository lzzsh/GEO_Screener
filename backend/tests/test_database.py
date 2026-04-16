import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_run_sqlite_migrations_adds_missing_label_schema_column(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE screening_tasks (
            id INTEGER PRIMARY KEY,
            name VARCHAR(256) NOT NULL,
            source VARCHAR(16) NOT NULL,
            search_query TEXT,
            status VARCHAR(32),
            total INTEGER,
            candidate_count INTEGER,
            processed INTEGER,
            included_count INTEGER,
            excluded_count INTEGER,
            uncertain_count INTEGER,
            criteria_text TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at DATETIME
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE screening_results (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            dataset_id VARCHAR(64) NOT NULL,
            title VARCHAR(512),
            decision VARCHAR(16),
            confidence FLOAT,
            summary TEXT,
            rule_checks TEXT,
            status VARCHAR(16),
            error_msg TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    from backend.database import _run_sqlite_migrations

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as async_conn:
        await _run_sqlite_migrations(async_conn)
    await engine.dispose()

    conn = sqlite3.connect(db_path)
    task_columns = {row[1] for row in conn.execute("PRAGMA table_info(screening_tasks)").fetchall()}
    result_columns = {row[1] for row in conn.execute("PRAGMA table_info(screening_results)").fetchall()}
    conn.close()

    assert "label_schema" in task_columns
    assert {"gse_type", "pubdate", "update_date", "has_raw_data", "n_samples"}.issubset(result_columns)


@pytest.mark.asyncio
async def test_init_db_enables_wal_mode_for_file_backed_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "wal.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import importlib
    import backend.database as database

    database = importlib.reload(database)
    await database.init_db()
    await database.engine.dispose()

    conn = sqlite3.connect(db_path)
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert journal_mode.lower() == "wal"
