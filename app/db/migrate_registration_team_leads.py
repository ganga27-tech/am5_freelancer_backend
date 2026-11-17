from sqlalchemy import text

from app.db.session import engine


async def ensure_registration_team_lead_columns() -> None:
    statements = (
        """
        ALTER TABLE vendors
        ADD COLUMN IF NOT EXISTS registration_team_lead_id BIGINT
            REFERENCES employees(id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE vendors
        ADD COLUMN IF NOT EXISTS registration_team_lead_assigned_at TIMESTAMP WITH TIME ZONE
        """,
        """
        ALTER TABLE vendors
        ADD COLUMN IF NOT EXISTS registration_team_lead_remark TEXT
        """,
        """
        ALTER TABLE vendors
        ADD COLUMN IF NOT EXISTS registration_team_lead_remark_updated_at TIMESTAMP WITH TIME ZONE
        """,
        """
        ALTER TABLE vendors
        ADD COLUMN IF NOT EXISTS registration_team_lead_remark_updated_by BIGINT
            REFERENCES employees(id) ON DELETE SET NULL
        """,
    )
    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))
