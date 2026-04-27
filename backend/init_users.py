"""Run once at container startup to seed default users."""
import asyncio
import os
from sqlalchemy import select
from backend.database import engine, init_db
from backend.database import AsyncSessionLocal
from backend.models import User
from backend.auth import hash_password

DEFAULT_USERS = [
    ("admin1", "admin1@geo.local", "admin123"),
    ("admin2", "admin2@geo.local", "admin123"),
    ("admin3", "admin3@geo.local", "admin123"),
    ("admin4", "admin4@geo.local", "admin123"),
    ("admin5", "admin5@geo.local", "admin123"),
]

async def seed():
    await init_db()
    async with AsyncSessionLocal() as db:
        for username, email, password in DEFAULT_USERS:
            exists = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
            if not exists:
                db.add(User(username=username, email=email, hashed_password=hash_password(password)))
                print(f"Created user: {username}")
            else:
                print(f"User already exists: {username}")
        await db.commit()

if __name__ == "__main__":
    asyncio.run(seed())
