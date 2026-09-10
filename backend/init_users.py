"""Compatibility startup command: initialize storage without preset accounts."""
import asyncio
from backend.database import init_db, engine


async def seed():
    await init_db()
    print('Database initialized. Register your own account through /auth/register.')


async def main():
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
