import paramiko

def run_query():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('76.13.245.174', username='root', password='Am5royal@2026')

    script = """
import asyncio
import json
import re
from sqlalchemy import text
from app.db.session import engine

async def check():
    async with engine.connect() as conn:
        res = await conn.execute(text('''
            SELECT 
                v.id as vendor_id,
                v.user_id,
                v.first_name,
                v.last_name,
                v.business_name,
                v.mobile,
                v.status,
                v.is_premium,
                v.city,
                v.district,
                v.state,
                v.pincode,
                v.address,
                v.created_at,
                u.is_active as user_active,
                u.otp_verified
            FROM vendors v
            LEFT JOIN users u ON v.user_id = u.id
            ORDER BY v.id
        '''))
        all_vendors = [dict(r) for r in res.mappings().fetchall()]

    ap_districts = {
        'anantapur', 'ananthapur', 'chittoor', 'chittor', 'east godavari', 'guntur', 'krishna', 
        'kurnool', 'prakasam', 'srikakulam', 'sri potti sriramulu nellore', 'sps nellore', 'nellore', 
        'visakhapatnam', 'vizag', 'visakhapatanam', 'vizianagaram', 'west godavari', 'ysr', 'kadapa', 
        'ysr kadapa', 'parvathipuram manyam', 'alluri sitharama raju', 'anakapalli', 'kakinada', 
        'konaseema', 'eluru', 'ntr', 'bapatla', 'palnadu', 'sri sathya sai', 'annamayya', 
        'tirupati', 'tirupathi', 'nandyal'
    }

    ap_major_cities = {
        'visakhapatnam', 'vizag', 'visakhapatanam', 'vijayawada', 'guntur', 'nellore', 'kurnool', 
        'rajahmundry', 'tirupati', 'tirupathi', 'kakinada', 'kadapa', 'anantapur', 'ananthapur', 
        'vizianagaram', 'eluru', 'ongole', 'nandyal', 'machilipatnam', 'adoni', 'tenali', 'proddatur', 
        'chittoor', 'hindupur', 'bhimavaram', 'madanapalle', 'guntakal', 'srikakulam', 'dharmavaram', 
        'gudivada', 'narasaraopet', 'tadipatri', 'mangalagiri', 'tadepalligudem', 'chilakaluripet',
        'chittoor', 'tanuku', 'rayachoti', 'kavali', 'chirala', 'palakollu'
    }

    def clean_str(s):
        return (s or '').strip()

    def is_ap_state(s):
        s_low = s.lower().replace(' ', '').replace('-', '')
        return any(x in s_low for x in ['andhrapradesh', 'andrapradesh', 'andhra', 'andra']) or s.strip().upper() == 'AP'

    categorized = []

    for v in all_vendors:
        st = clean_str(v['state'])
        city = clean_str(v['city'])
        dist = clean_str(v['district'])
        addr = clean_str(v['address'])
        pin = clean_str(v['pincode'])

        matched = False
        reasons = []

        # 1. State check
        if is_ap_state(st):
            matched = True
            reasons.append(f"state: '{st}'")

        # 2. Pincode check: 515000 to 535999 is Andhra Pradesh postal circle
        if len(pin) == 6 and pin.isdigit():
            p_int = int(pin)
            if 515000 <= p_int <= 535999:
                matched = True
                reasons.append(f"ap_pincode: {pin}")

        # 3. District match (exact normalized word match)
        dist_norm = dist.lower().strip()
        if dist_norm in ap_districts:
            matched = True
            reasons.append(f"district: '{dist}'")

        # 4. City match
        city_norm = city.lower().strip()
        if city_norm in ap_major_cities:
            matched = True
            reasons.append(f"city: '{city}'")

        if matched:
            categorized.append((v, reasons))

    print(f"=== TOTAL VENDORS IN DATABASE: {len(all_vendors)} ===")
    print(f"=== TOTAL VENDORS IDENTIFIED IN ANDHRA PRADESH: {len(categorized)} ===\\n")

    # Status breakdown
    status_counts = {}
    city_counts = {}
    district_counts = {}
    state_strings = {}

    for v, reasons in categorized:
        st_val = v['status'] or 'unknown'
        status_counts[st_val] = status_counts.get(st_val, 0) + 1

        c_val = v['city'] or 'Not Specified'
        city_counts[c_val] = city_counts.get(c_val, 0) + 1

        d_val = v['district'] or 'Not Specified'
        district_counts[d_val] = district_counts.get(d_val, 0) + 1

        s_val = v['state'] or 'Not Specified'
        state_strings[s_val] = state_strings.get(s_val, 0) + 1

    print("--- Status Breakdown ---")
    for s, c in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {s}: {c}")

    print("\\n--- State Field Values ---")
    for s, c in sorted(state_strings.items(), key=lambda x: x[1], reverse=True):
        print(f"  '{s}': {c}")

    print("\\n--- Top Cities/Locations in AP ---")
    for c, cnt in sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {c}: {cnt}")

    print("\\n--- Top Districts in AP ---")
    for d, cnt in sorted(district_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {d}: {cnt}")

    print("\\n--- Detailed List of all AP Vendors ---")
    for idx, (v, reasons) in enumerate(categorized, 1):
        name = v['business_name'] or f\"{v['first_name'] or ''} {v['last_name'] or ''}\".strip() or 'Unnamed'
        print(f"{idx}. ID: {v['vendor_id']} | UserID: {v['user_id']} | Name: {name} | Phone: {v['mobile']} | Status: {v['status']} | City: {v['city']} | Dist: {v['district']} | State: {v['state']} | PIN: {v['pincode']} | Matched by: {', '.join(reasons)}")

asyncio.run(check())
"""
    sftp = client.open_sftp()
    with sftp.open('/root/am5-backend/scratch/check_ap_refined.py', 'w') as f:
        f.write(script)
    sftp.close()

    stdin, stdout, stderr = client.exec_command('docker exec -i -w /app -e PYTHONPATH=/app am5_backend python /app/scratch/check_ap_refined.py')
    out = stdout.read().decode('utf-8', errors='replace')
    print(out)
    err = stderr.read().decode('utf-8', errors='replace')
    if err:
        print('ERR:', err)
    client.close()

if __name__ == '__main__':
    run_query()
