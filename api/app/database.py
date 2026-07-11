import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]
_async_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://").split("?")[0]

engine = create_async_engine(_async_url, echo=False, connect_args={"ssl": "require"})
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
