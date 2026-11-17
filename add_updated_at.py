import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE main_categories
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE
            DEFAULT NOW()
        """))
        print("SUCCESS: updated_at column added")

    await engine.dispose()

asyncio.run(main())
