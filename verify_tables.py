import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' "
            "AND (tablename LIKE 're_%' OR tablename = 'vendor_media') "
            "ORDER BY tablename"
        ))
        print("\nREAL ESTATE TABLES:")
        for row in result.fetchall():
            print(row[0])

    await engine.dispose()

asyncio.run(main())
