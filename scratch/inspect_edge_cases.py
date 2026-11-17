import paramiko

def inspect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('76.13.245.174', username='root', password='Am5royal@2026')

    script = """
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def run():
    async with engine.connect() as conn:
        res = await conn.execute(text('''
            SELECT id, user_id, business_name, city, district, state, pincode, address
            FROM vendors
            WHERE id IN (700, 777) OR state IN ('Telanga', 'India', 'Vijayawada')
        '''))
        for r in res.mappings().fetchall():
            print(dict(r))

asyncio.run(run())
"""
    sftp = client.open_sftp()
    with sftp.open('/root/am5-backend/scratch/temp_inspect_tg.py', 'w') as f:
        f.write(script)
    sftp.close()

    stdin, stdout, stderr = client.exec_command('docker exec -i -w /app -e PYTHONPATH=/app am5_backend python /app/scratch/temp_inspect_tg.py')
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print('ERR:', err)
    client.close()

if __name__ == '__main__':
    inspect()
