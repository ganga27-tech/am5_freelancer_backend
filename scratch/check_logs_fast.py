import paramiko

HOST = "76.13.245.174"
USER = "root"
PASS = "Am5royal@2026"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

print("--- am5_backend LOGS ---")
stdin, stdout, stderr = ssh.exec_command("docker logs am5_backend --tail 60", timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

print("--- am5_backend_dev LOGS ---")
stdin, stdout, stderr = ssh.exec_command("docker logs am5_backend_dev --tail 60", timeout=10)
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
