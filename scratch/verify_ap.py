import paramiko

def verify_all():
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
            SELECT id, user_id, business_name, first_name, last_name, city, district, state, pincode, address, status, is_premium
            FROM vendors
            ORDER BY id
        '''))
        all_v = [dict(r) for r in res.mappings().fetchall()]

    print(f"Total vendors in DB: {len(all_v)}")

    # Group 1: Explicit AP in state field
    g1 = []
    # Group 2: State not AP, but clearly in AP (e.g. Vijayawada, or AP pincode & city)
    g2 = []
    # Group 3: Ambiguous (e.g. Hyderabad address but AP district name)
    g3 = []

    ap_state_keywords = ['andhra', 'andra']

    for v in all_v:
        st = (v.get('state') or '').strip()
        st_low = st.lower()
        pin = (v.get('pincode') or '').strip()
        city = (v.get('city') or '').strip()
        dist = (v.get('district') or '').strip()
        addr = (v.get('address') or '').strip()

        if any(k in st_low for k in ap_state_keywords) or st.upper() == 'AP':
            g1.append(v)
        elif st.lower() == 'vijayawada':
            g2.append((v, "State entered as 'Vijayawada' (Krishna/NTR dist, AP)"))
        elif pin.startswith(('51', '52', '53')) and len(pin) == 6 and pin.isdigit():
            p_int = int(pin)
            if 515000 <= p_int <= 535999:
                g2.append((v, f"AP postal pincode {pin}, State: '{st}', City: '{city}', Addr: '{addr}'"))
        elif v['id'] in (700, 777):
            g3.append((v, f"District: '{dist}', but City: '{city}', State: '{st}', Pincode: {pin}"))

    print(f"\\n1. Vendors with explicit Andhra Pradesh state: {len(g1)}")
    for v in g1:
        pass # we have these

    print(f"\\n2. Additional vendors located in Andhra Pradesh (non-standard state entry): {len(g2)}")
    for v, reason in g2:
        print(f"  - ID #{v['id']}: {v['business_name']} | City: {v['city']} | State: '{v['state']}' | PIN: {v['pincode']} | Reason: {reason}")

    print(f"\\n3. Ambiguous (Hyderabad / Telangana with AP district name): {len(g3)}")
    for v, reason in g3:
        print(f"  - ID #{v['id']}: {v['business_name']} | City: {v['city']} | State: '{v['state']}' | PIN: {v['pincode']} | Reason: {reason}")

    # Let's inspect status of Group 1 + Group 2
    ap_vendors_total = g1 + [x[0] for x in g2]
    status_map = {}
    for v in ap_vendors_total:
        s = v.get('status') or 'None'
        status_map[s] = status_map.get(s, 0) + 1

    print(f"\\n--- Total Confirmed AP Vendors: {len(ap_vendors_total)} ---")
    print("Status Breakdown:")
    for s, cnt in sorted(status_map.items(), key=lambda x: x[1], reverse=True):
        print(f"  {s}: {cnt}")

    # District Breakdown
    dist_map = {}
    for v in ap_vendors_total:
        d = v.get('district') or 'Unspecified / None'
        dist_map[d] = dist_map.get(d, 0) + 1
    print("\\nDistrict Breakdown:")
    for d, cnt in sorted(dist_map.items(), key=lambda x: x[1], reverse=True):
        print(f"  {d}: {cnt}")

    # City Breakdown
    city_map = {}
    for v in ap_vendors_total:
        c = v.get('city') or 'Unspecified / None'
        city_map[c] = city_map.get(c, 0) + 1
    print("\\nTop Cities:")
    for c, cnt in sorted(city_map.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {c}: {cnt}")

asyncio.run(run())
"""
    sftp = client.open_sftp()
    with sftp.open('/root/am5-backend/scratch/verify_ap_vendors.py', 'w') as f:
        f.write(script)
    sftp.close()

    stdin, stdout, stderr = client.exec_command('docker exec -i -w /app -e PYTHONPATH=/app am5_backend python /app/scratch/verify_ap_vendors.py')
    print(stdout.read().decode())
    client.close()

if __name__ == '__main__':
    verify_all()
