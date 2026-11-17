import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import URL
from app.core.config import settings

async def main():
    url = URL.create(
        "postgresql+asyncpg",
        username=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_SERVER,
        port=int(settings.POSTGRES_PORT),
        database=settings.POSTGRES_DB,
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            print("DATABASE CONNECTION SUCCESS")
    except Exception as e:
        print("DATABASE CONNECTION FAILED:", repr(e))
    finally:
        await engine.dispose()

asyncio.run(main())
