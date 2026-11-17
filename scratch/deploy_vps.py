import os
import time
import paramiko

VPS_HOST = "76.13.245.174"
VPS_PORT = 22
VPS_USER = "root"
VPS_PASS = "Am5royal@2026"
REMOTE_APP_DIR = "/root/am5-backend/app"
LOCAL_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))

def upload_directory(sftp, local_dir, remote_dir):
    try:
        sftp.stat(remote_dir)
    except IOError:
        print(f"Creating remote directory: {remote_dir}")
        sftp.mkdir(remote_dir)

    for item in os.listdir(local_dir):
        if item == "__pycache__" or item.endswith(".pyc"):
            continue
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}"

        if os.path.isdir(local_path):
            upload_directory(sftp, local_path, remote_path)
        else:
            print(f"Uploading: {local_path} -> {remote_path}")
            sftp.put(local_path, remote_path)

def main():
    print(f"Connecting to VPS {VPS_HOST} via SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=30)
    print("SSH Connected successfully.")

    print(f"Syncing local {LOCAL_APP_DIR} to {REMOTE_APP_DIR} via SFTP...")
    sftp = ssh.open_sftp()
    upload_directory(sftp, LOCAL_APP_DIR, REMOTE_APP_DIR)
    sftp.close()
    print("Files uploaded successfully.")

    print("Updating Docker container am5_backend...")
    # Update container files & restart
    commands = [
        "docker cp /root/am5-backend/app/. am5_backend:/app/app/",
        "docker restart am5_backend"
    ]
    for cmd in commands:
        print(f"Running: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')
        if out:
            print(f"Stdout: {out}")
        if err:
            print(f"Stderr: {err}")

    print("Waiting 5 seconds for backend to initialize...")
    time.sleep(5)

    print("Checking Docker logs...")
    stdin, stdout, stderr = ssh.exec_command("docker logs am5_backend --tail 40")
    logs = stdout.read().decode('utf-8')
    print("=== DOCKER LOGS ===")
    print(logs)
    print("===================")

    # Test health check or API status
    stdin, stdout, stderr = ssh.exec_command("curl -s http://localhost:8000/docs -o /dev/null -w '%{http_code}'")
    status_code = stdout.read().decode('utf-8').strip()
    print(f"API Docs Health Check HTTP Status: {status_code}")

    ssh.close()
    print("Deployment completed!")

if __name__ == "__main__":
    main()
