"""Creates/updates everything the category modules (Real Estate, ...) need: columns, tables, seed data. Idempotent.

Run manually (recommended BEFORE deploying new code):
    python -m app.db.migrate_real_estate               # new Real Estate category starts HIDDEN
    python -m app.db.migrate_real_estate --activate    # show it in the apps (after app/panel release)
    python -m app.db.migrate_real_estate --deactivate  # hide it again
It also runs first at app startup, in its own transaction, so a failure in the
unrelated legacy startup block can't roll these changes back. Errors are logged.
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from app.db.base_class import Base
from app.db.session import engine

# Columns on EXISTING tables (create_all never adds columns).
COLUMN_STATEMENTS = [
    "ALTER TABLE IF EXISTS main_categories ADD COLUMN IF NOT EXISTS form_type VARCHAR NOT NULL DEFAULT 'service_list'",
    "ALTER TABLE IF EXISTS cities ADD COLUMN IF NOT EXISTS district VARCHAR",
]

# New tables owned by category modules.
CATEGORY_TABLE_PREFIXES = ("re_",)
CATEGORY_TABLE_NAMES = {"vendor_media"}


def _category_tables():
    import app.models  # noqa: F401  (registers every model, incl. category modules)
    # Parent tables (vendors, sub_categories, ...) must be registered for the FKs to resolve.
    import app.main  # noqa: F401
    return [
        t for t in Base.metadata.sorted_tables
        if t.name in CATEGORY_TABLE_NAMES or t.name.startswith(CATEGORY_TABLE_PREFIXES)
    ]


async def seed_coverage_location_master() -> None:
    """Idempotently seed normalized Real Estate state/district IDs from approved source data."""
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.categories.real_estate.models import ReCoverageState, ReCoverageDistrict

    source = Path(__file__).resolve().parents[1] / "categories" / "real_estate" / "location_data.json"
    records = json.loads(source.read_text(encoding="utf-8"))
    async with AsyncSessionLocal() as session:
        states = {}
        for record in records:
            code, name = record["code"], record["name"]
            state = (await session.execute(
                select(ReCoverageState).where(ReCoverageState.code == code)
            )).scalars().first()
            if state is None:
                state = ReCoverageState(code=code, name=name)
                session.add(state)
                await session.flush()
            states[code] = state
        for record in records:
            state = states[record["code"]]
            for district_data in record.get("districts", []):
                code, name = district_data["code"], district_data["name"]
                existing = (await session.execute(
                    select(ReCoverageDistrict.id).where(
                        ReCoverageDistrict.state_id == state.id,
                        ReCoverageDistrict.code == code,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    session.add(ReCoverageDistrict(state_id=state.id, code=code, name=name))
        await session.commit()

async def apply_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in COLUMN_STATEMENTS:
            await conn.execute(text(stmt))
        tables = _category_tables()
        if tables:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))


    await seed_coverage_location_master()

async def seed_categories(activate=None) -> None:
    """Idempotent master data: Real Estate category, subcategories, property types, BHK, furniture."""
    from app.categories.registry import CATEGORIES
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            for c in CATEGORIES:
                await c.seed(session, activate)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _main(activate=None) -> None:
    await apply_migrations()
    await seed_categories(activate)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--activate", action="store_true", help="Show the Real Estate category in the apps")
    g.add_argument("--deactivate", action="store_true", help="Hide the Real Estate category from the apps")
    a = ap.parse_args()
    asyncio.run(_main(True if a.activate else False if a.deactivate else None))
    state = "ACTIVATED (visible in apps)" if a.activate else "DEACTIVATED (hidden)" if a.deactivate else "visibility unchanged (new category starts hidden)"
    print(f"OK: category columns, tables and seed data are present. Real Estate: {state}.")
