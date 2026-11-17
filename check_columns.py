import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'main_categories'
            ORDER BY ordinal_position
        """))
        print("MAIN CATEGORIES COLUMNS:")
        for row in result.fetchall():
            print(row[0])
    await engine.dispose()

asyncio.run(main())
