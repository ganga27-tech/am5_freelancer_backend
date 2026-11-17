import paramiko

def check_null_states():
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
            SELECT id, user_id, business_name, city, district, state, pincode, address, status
            FROM vendors
            WHERE state IS NULL OR TRIM(state) = ''
        '''))
        null_state_vendors = [dict(r) for r in res.mappings().fetchall()]
        print(f"Total vendors with NULL or empty state: {len(null_state_vendors)}")
        
        ap_candidates = []
        for v in null_state_vendors:
            pin = str(v.get('pincode') or '').strip()
            city = str(v.get('city') or '').strip().lower()
            dist = str(v.get('district') or '').strip().lower()
            addr = str(v.get('address') or '').strip().lower()

            is_ap = False
            reasons = []
            if len(pin) == 6 and pin.isdigit():
                p = int(pin)
                if 515000 <= p <= 535999:
                    is_ap = True
                    reasons.append(f"pincode {pin}")
            if any(x in addr or x in city or x in dist for x in ['andhra', 'vizag', 'visakhapatnam', 'vijayawada', 'guntur', 'kurnool', 'nellore', 'kadapa', 'tirupati', 'kakinada', 'rajahmundry', 'anantapur']):
                is_ap = True
                reasons.append(f"text match: city='{city}', dist='{dist}', addr='{addr}'")

            if is_ap:
                ap_candidates.append((v, reasons))

        print(f"Vendors with NULL state that appear to be in AP: {len(ap_candidates)}")
        for v, reasons in ap_candidates:
            print(f"ID: {v['id']} | Name: {v['business_name']} | City: {v['city']} | Dist: {v['district']} | Pin: {v['pincode']} | Address: {v['address']} | Reasons: {reasons}")

asyncio.run(run())
"""
    sftp = client.open_sftp()
    with sftp.open('/root/am5-backend/scratch/temp_null_states.py', 'w') as f:
        f.write(script)
    sftp.close()

    stdin, stdout, stderr = client.exec_command('docker exec -i -w /app -e PYTHONPATH=/app am5_backend python /app/scratch/temp_null_states.py')
    print(stdout.read().decode())
    client.close()

if __name__ == '__main__':
    check_null_states()
