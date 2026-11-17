import os, sys
sys.path.insert(0, os.path.abspath("."))
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.employee import Employee
from sqlalchemy import select, func

async def check_roles():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Employee.role, func.count(Employee.id)).group_by(Employee.role)
        )
        print("Employee Roles Count in Database:")
        for role, count in res.all():
            print(f" - {role}: {count} user(s)")

if __name__ == "__main__":
    asyncio.run(check_roles())
