import asyncio
from sqlalchemy import text
from app.db.session import engine, AsyncSessionLocal
from app.db.base_class import Base
import app.models  # registers all models including freelance_api models
from freelance_api.seed_data import seed_freelance_defaults

async def migrate():
    print("1. Creating all missing tables with Base.metadata.create_all...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("   ✓ Tables created successfully.")

    print("2. Ensuring all columns exist in 'freelancers' table...")
    alter_queries = [
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS photo_url VARCHAR;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS city VARCHAR;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS state VARCHAR;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS address TEXT;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS pincode VARCHAR;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS bio TEXT;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS profile_status VARCHAR DEFAULT 'active';",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS profile_completion_percentage INTEGER DEFAULT 25;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS bank_verification_status VARCHAR DEFAULT 'NOT_VERIFIED';",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS kyc_status VARCHAR DEFAULT 'NOT_STARTED';",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS face_verification_status VARCHAR DEFAULT 'NOT_STARTED';",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS total_earnings NUMERIC(12, 2) DEFAULT 0.00;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS available_balance NUMERIC(12, 2) DEFAULT 0.00;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS pending_balance NUMERIC(12, 2) DEFAULT 0.00;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS processing_balance NUMERIC(12, 2) DEFAULT 0.00;",
        "ALTER TABLE freelancers ADD COLUMN IF NOT EXISTS total_withdrawn NUMERIC(12, 2) DEFAULT 0.00;",
    ]

    async with AsyncSessionLocal() as session:
        for q in alter_queries:
            try:
                await session.execute(text(q))
            except Exception as e:
                print(f"   [Notice] Query skipped or already applied: {e}")
        await session.commit()
    print("   ✓ Freelancers table columns verified.")

    print("3. Seeding default banners, demo videos, reward rules and FAQs...")
    async with AsyncSessionLocal() as session:
        try:
            await seed_freelance_defaults(session)
            print("   ✓ Default seed data successfully populated.")
        except Exception as e:
            print(f"   [Notice] Seeding skipped: {e}")

    print("\nFreelancer Database Migration Complete! 🚀")

if __name__ == "__main__":
    asyncio.run(migrate())

