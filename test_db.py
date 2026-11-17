import asyncio
import asyncpg
import getpass

async def main():
    password = getpass.getpass("Enter PostgreSQL password: ")
    try:
        conn = await asyncpg.connect(
            user="postgres",
            password=password,
            database="am5royal",
            host="localhost",
            port=5432
        )
        print("DATABASE CONNECTION SUCCESS")
        await conn.close()
    except Exception as e:
        print("DATABASE CONNECTION FAILED:", str(e))

asyncio.run(main())
