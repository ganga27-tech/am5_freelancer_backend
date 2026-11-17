import paramiko

HOST = "76.13.245.174"
USER = "root"
PASSWORD = "Am5royal@2026"

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    
    script = """
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.employee import Employee
from app.core.security import get_password_hash
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Employee).order_by(Employee.id))
        employees = res.scalars().all()
        print("=== ALL EMPLOYEES IN DB ===")
        lead_found = False
        for e in employees:
            print(f"ID: {e.id} | Name: {e.first_name} {e.last_name or ''} | Email: {e.email} | Phone: {e.phone_number} | Role: {e.role} | Status: {e.status}")
            if e.role in ['telecaller_lead', 'team_lead', 'admin', 'super_admin']:
                lead_found = True
        
        # If no telecaller_lead exists, create one
        lead_check = await db.execute(select(Employee).where((Employee.email == 'lead.telecaller@am5royal.com') | (Employee.phone_number == '9000000002')))
        lead_user = lead_check.scalars().first()
        if not lead_user:
            lead_emp = Employee(
                first_name="Lead",
                last_name="Manager",
                email="lead.telecaller@am5royal.com",
                phone_number="9000000002",
                hashed_password=get_password_hash("Lead@1234"),
                role="telecaller_lead",
                status="active"
            )
            db.add(lead_emp)
            await db.commit()
            print("\\n[+] Created new Telecaller Lead account:")
            print("    Email/Identifier: lead.telecaller@am5royal.com or 9000000002")
            print("    Password: Lead@1234")
            print("    Role: telecaller_lead")
        else:
            print(f"\\nExisting Telecaller Lead: {lead_user.email} (Phone: {lead_user.phone_number}, Role: {lead_user.role})")

asyncio.run(run())
"""
    stdin, stdout, stderr = ssh.exec_command('docker exec -i am5_backend python')
    stdin.write(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(out)
    if err:
        print("[STDERR]:", err)
    
    ssh.close()

if __name__ == "__main__":
    main()
