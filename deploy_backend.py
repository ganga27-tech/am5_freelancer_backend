import os
import sys
import time
import paramiko

HOST = "76.13.245.174"
USER = "root"
PASSWORD = "Am5royal@2026"
REMOTE_PATH = "/root/am5-backend"
LOCAL_APP_PATH = os.path.abspath("app")

def sftp_upload_dir(sftp, local_dir, remote_dir):
    try:
        sftp.mkdir(remote_dir) 
    except IOError:
        pass

    for root, dirs, files in os.walk(local_dir):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        rel_path = os.path.relpath(root, local_dir)
        if rel_path == ".":
            dest_dir = remote_dir
        else:
            dest_dir = os.path.join(remote_dir, rel_path).replace("\\", "/")
            try:
                sftp.mkdir(dest_dir)
            except IOError:
                pass

        for f in files:
            if f.endswith(".pyc") or f.endswith(".DS_Store"):
                continue
            local_file = os.path.join(root, f)
            remote_file = os.path.join(dest_dir, f).replace("\\", "/")
            print(f"Uploading: {rel_path}/{f} -> {remote_file}")
            sftp.put(local_file, remote_file)

def main():
    print(f"[*] Connecting to {HOST} via SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    print("[+] Connected!")

    print("[*] Opening SFTP...")
    sftp = ssh.open_sftp()
    
    print("[*] Uploading app directory and alter scripts...")
    sftp_upload_dir(sftp, LOCAL_APP_PATH, f"{REMOTE_PATH}/app")
    if os.path.exists("alter_db_columns.py"):
        sftp.put(os.path.abspath("alter_db_columns.py"), f"{REMOTE_PATH}/alter_db_columns.py")
    sftp.close()
    print("[+] Files uploaded successfully!")

    print("[*] Copying files to am5_backend Docker container, running DB alter & restarting...")
    cmd = (
        f"docker cp {REMOTE_PATH}/app am5_backend:/app/ && "
        f"docker cp {REMOTE_PATH}/alter_db_columns.py am5_backend:/app/alter_db_columns.py && "
        "docker exec am5_backend python /app/alter_db_columns.py && "
        "docker restart am5_backend"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(f"[STDOUT]: {out}")
    if err:
        print(f"[STDERR]: {err}")

    print("[*] Waiting 5 seconds for backend to initialize...")
    time.sleep(5)

    print("[*] Checking container logs...")
    stdin, stdout, stderr = ssh.exec_command("docker logs --tail 30 am5_backend")
    logs = stdout.read().decode()
    print("----- CONTAINER LOGS -----")
    print(logs)
    print("--------------------------")

    ssh.close()
    print("[+] Backend Deployment Completed Successfully!")

if __name__ == "__main__":
    main()
