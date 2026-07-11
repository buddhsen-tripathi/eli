"""Create all tables. Run once against a fresh database:

    uv run python scripts/init_db.py

For real migrations later, swap this for Alembic. This is the quick-start path.
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from app.database import engine  # noqa: E402
from app.db_models import Base  # noqa: E402


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("tables created:", ", ".join(Base.metadata.tables))


if __name__ == "__main__":
    asyncio.run(main())
