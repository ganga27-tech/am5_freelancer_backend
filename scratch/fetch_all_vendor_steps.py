import paramiko
import json

def fetch_data():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('76.13.245.174', username='root', password='Am5royal@2026')

    script = """
import asyncio
import json
from sqlalchemy import text
from app.db.session import engine

async def run():
    query = text('''
        SELECT 
            u.id as user_id,
            COALESCE(u.mobile, 'N/A') as user_mobile,
            COALESCE(u.email, 'N/A') as user_email,
            u.otp_verified,
            u.is_active as user_is_active,
            u.created_at as user_created_at,
            v.id as vendor_id,
            COALESCE(v.first_name, '') as first_name,
            COALESCE(v.last_name, '') as last_name,
            COALESCE(v.business_name, '') as business_name,
            COALESCE(v.mobile, '') as vendor_mobile,
            COALESCE(v.city, '') as city,
            COALESCE(v.district, '') as district,
            COALESCE(v.state, '') as state,
            COALESCE(v.pincode, '') as pincode,
            COALESCE(v.address, '') as address,
            COALESCE(v.status, '') as vendor_status,
            COALESCE(v.is_premium, false) as is_premium,
            (
                SELECT COUNT(*) FROM vendor_sub_categories vsc WHERE vsc.vendor_id = v.id
            ) as subcategories_count,
            (
                SELECT COUNT(*) FROM vendor_services vsr WHERE vsr.vendor_id = v.id
            ) as services_count,
            (
                SELECT COUNT(*) FROM vendor_availability va WHERE va.vendor_id = v.id AND va.is_available = true
            ) as slots_count,
            (
                SELECT COUNT(*) FROM vendor_documents vd WHERE vd.vendor_id = v.id
            ) as documents_count,
            (
                SELECT vs.status 
                FROM vendor_subscriptions vs 
                WHERE vs.vendor_id = v.id 
                ORDER BY vs.id DESC LIMIT 1
            ) as latest_sub_status,
            (
                SELECT sp.name 
                FROM vendor_subscriptions vs 
                JOIN subscription_plans sp ON vs.subscription_plan_id = sp.id
                WHERE vs.vendor_id = v.id 
                ORDER BY vs.id DESC LIMIT 1
            ) as latest_sub_plan
        FROM users u
        LEFT JOIN vendors v ON v.user_id = u.id
        WHERE u.role LIKE '%VENDOR%'
        ORDER BY u.id ASC
    ''')

    async with engine.connect() as conn:
        res = await conn.execute(query)
        rows = [dict(r) for r in res.mappings().fetchall()]

    for r in rows:
        for k, v in r.items():
            if hasattr(v, 'isoformat'):
                r[k] = v.isoformat()

    with open('/app/scratch/all_vendors_steps.json', 'w') as f:
        json.dump(rows, f, indent=2)

    print(f"Total vendor users dumped: {len(rows)}")

asyncio.run(run())
"""
    sftp = client.open_sftp()
    with sftp.open('/root/am5-backend/scratch/dump_vendor_steps.py', 'w') as f:
        f.write(script)
    sftp.close()

    stdin, stdout, stderr = client.exec_command('docker exec -i -w /app -e PYTHONPATH=/app am5_backend python /app/scratch/dump_vendor_steps.py')
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print('ERR:', err)

    sftp = client.open_sftp()
    sftp.get('/root/am5-backend/scratch/all_vendors_steps.json', 'd:/fb/all_vendors_steps.json')
    sftp.close()
    client.close()
    print("Downloaded all_vendors_steps.json successfully.")

if __name__ == '__main__':
    fetch_data()
