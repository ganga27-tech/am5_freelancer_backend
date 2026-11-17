import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        print("Altering vendors table...")
        
        # We need to add columns to the DB manually if they don't exist
        queries = [
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS email VARCHAR;",
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS alternative_number VARCHAR;",
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS father_name VARCHAR;",
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS additional_business_info TEXT;",
            """
            CREATE TABLE IF NOT EXISTS vendor_audit_logs (
                id BIGSERIAL PRIMARY KEY,
                vendor_id BIGINT NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
                employee_id BIGINT REFERENCES employees(id) ON DELETE SET NULL,
                employee_name VARCHAR(255),
                employee_role VARCHAR(50),
                action_type VARCHAR(100) NOT NULL,
                description TEXT,
                details JSONB,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
            );
            """,
            "CREATE INDEX IF NOT EXISTS ix_vendor_audit_logs_vendor_id ON vendor_audit_logs (vendor_id);",
            "CREATE INDEX IF NOT EXISTS ix_vendor_audit_logs_employee_id ON vendor_audit_logs (employee_id);",
            "CREATE INDEX IF NOT EXISTS ix_vendor_audit_logs_created_at ON vendor_audit_logs (created_at DESC);"
        ]
        
        for query in queries:
            try:
                await db.execute(text(query))
                print(f"Executed: {query.strip()[:60]}...")
            except Exception as e:
                print(f"Error executing query: {e}")
                
        await db.commit()
        print("Done")

if __name__ == "__main__":
    asyncio.run(main())
