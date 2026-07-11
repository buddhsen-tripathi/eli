"""Create/upgrade tables. Idempotent — safe to re-run:

    uv run --env-file ../.env python scripts/init_db.py

`create_all` creates any missing tables but does NOT alter existing ones, so new
columns on already-created tables are added explicitly below with
`ADD COLUMN IF NOT EXISTS`. For anything beyond additive columns, move to Alembic.
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.db_models import Base  # noqa: E402

# Additive column migrations for tables that predate the column.
COLUMN_MIGRATIONS = [
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS checkin_days JSONB DEFAULT '[1, 3, 7]'::jsonb",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS el_conversation_id VARCHAR",
]


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in COLUMN_MIGRATIONS:
            await conn.execute(text(stmt))
    print("tables ready:", ", ".join(Base.metadata.tables))
    print("column migrations applied:", len(COLUMN_MIGRATIONS))


if __name__ == "__main__":
    asyncio.run(main())
