import asyncio
from sqlalchemy import text
from app.db.session import engine

async def migrate():
    print("Running migration for visiting_charges column on vendors table...")
    async with engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE vendors 
            ADD COLUMN IF NOT EXISTS visiting_charges NUMERIC(10, 2);
        """))
        await conn.execute(text("""
            ALTER TABLE vendors 
            ADD COLUMN IF NOT EXISTS approx_visit_charge NUMERIC(10, 2);
        """))
        print("Successfully added/verified visiting_charges and approx_visit_charge on vendors table.")

if __name__ == "__main__":
    asyncio.run(migrate())
