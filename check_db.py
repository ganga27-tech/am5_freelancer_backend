import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI)
    try:
        async with engine.connect():
            print("SQLALCHEMY DATABASE CONNECTION SUCCESS")
    finally:
        await engine.dispose()

asyncio.run(main())
