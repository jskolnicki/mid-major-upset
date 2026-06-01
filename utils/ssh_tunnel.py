"""SSH tunnel for connecting to production database on VPS.

Same pattern as personal-website: if DB_SSH_HOST is set in .env,
an SSH tunnel is established and DB_TUNNEL_PORT is set so config.py
routes the connection through the tunnel.
"""

import atexit
import os
import socket
import subprocess
import sys
import time
from typing import Optional, Tuple

_active_tunnel_process = None


def is_ssh_tunnel_configured() -> bool:
    return bool(os.getenv("DB_SSH_HOST"))


def get_ssh_config() -> dict:
    return {
        "ssh_host": os.getenv("DB_SSH_HOST"),
        "ssh_port": int(os.getenv("DB_SSH_PORT", "22")),
        "ssh_user": os.getenv("DB_SSH_USER"),
        "ssh_key": os.getenv("DB_SSH_KEY"),
        "db_host": os.getenv("DB_HOST", "127.0.0.1"),
        "db_port": int(os.getenv("DB_PORT", "3306")),
        "db_name": os.getenv("DB_NAME"),
    }


def confirm_production_connection(config: dict) -> bool:
    if "--yes" in sys.argv or "-y" in sys.argv:
        return True

    if not sys.stdin.isatty():
        print("ERROR: SSH tunnel configured but running non-interactively.")
        print("Use --yes flag to skip confirmation in non-interactive mode.")
        return False

    print()
    print("\033[91m" + "!" * 70 + "\033[0m")
    print("\033[91m!!     WARNING: THIS WILL CONNECT TO THE PRODUCTION DATABASE       !!\033[0m")
    print("\033[91m" + "!" * 70 + "\033[0m")
    print()
    print(f"  SSH Host:  {config['ssh_user']}@{config['ssh_host']}")
    print(f"  Database:  {config['db_name']}")
    print()

    response = input("\033[93mContinue? [y/N]: \033[0m").strip().lower()
    return response in ("y", "yes")


def _find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_tunnel(port: int, timeout: int = 30) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(("127.0.0.1", port))
                s.settimeout(5)
                data = s.recv(1)
                if data:
                    return True
        except (socket.error, socket.timeout):
            pass
        time.sleep(0.5)
    return False


def create_ssh_tunnel(config: dict) -> Tuple[Optional[subprocess.Popen], int]:
    global _active_tunnel_process

    ssh_key = config["ssh_key"]
    if ssh_key:
        expanded_key = os.path.expanduser(ssh_key)
        if not os.path.exists(expanded_key):
            print(f"ERROR: SSH key file not found: {ssh_key}")
            sys.exit(1)

    local_port = _find_available_port()

    ssh_cmd = [
        "ssh",
        "-N",
        "-L", f'{local_port}:{config["db_host"]}:{config["db_port"]}',
        "-p", str(config["ssh_port"]),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=no",
        "-o", "ExitOnForwardFailure=yes",
    ]

    if ssh_key:
        ssh_cmd.extend(["-i", os.path.expanduser(ssh_key)])

    ssh_cmd.append(f'{config["ssh_user"]}@{config["ssh_host"]}')

    try:
        process = subprocess.Popen(
            ssh_cmd,
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        _active_tunnel_process = process

        print(f"Establishing SSH tunnel (port {local_port})...")
        if not _wait_for_tunnel(local_port, timeout=30):
            if process.poll() is not None:
                _, stderr = process.communicate()
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                print(f"ERROR: SSH tunnel process exited: {error_msg}")
            else:
                process.terminate()
                print("ERROR: SSH tunnel failed to establish within timeout")
            sys.exit(1)

        print(f"SSH tunnel established: localhost:{local_port} -> {config['db_host']}:{config['db_port']}")
        return process, local_port

    except FileNotFoundError:
        print("ERROR: 'ssh' command not found. Ensure OpenSSH is installed.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to create SSH tunnel: {e}")
        sys.exit(1)


def close_ssh_tunnel():
    global _active_tunnel_process
    if _active_tunnel_process:
        try:
            _active_tunnel_process.terminate()
            _active_tunnel_process.wait(timeout=5)
            print("SSH tunnel closed.")
        except Exception:
            try:
                _active_tunnel_process.kill()
            except Exception:
                pass
        _active_tunnel_process = None


def setup_ssh_tunnel_if_configured() -> Optional[int]:
    """Main entry point. Call BEFORE loading config/creating DB connections."""
    if not is_ssh_tunnel_configured():
        return None

    config = get_ssh_config()

    if not confirm_production_connection(config):
        print("Aborted.")
        sys.exit(0)

    process, local_port = create_ssh_tunnel(config)
    os.environ["DB_TUNNEL_PORT"] = str(local_port)
    return local_port


atexit.register(close_ssh_tunnel)
