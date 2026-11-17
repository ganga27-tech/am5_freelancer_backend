import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT current_database(), to_regclass('public.booking_offers')")
        )
        print("Database and table:", result.fetchone())
    await engine.dispose()

asyncio.run(main())
