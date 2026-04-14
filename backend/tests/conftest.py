import os
import pytest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

pytest_plugins = ['anyio']

@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    from backend.database import init_db
    await init_db()
