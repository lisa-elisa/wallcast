"""Spells launcher. Run via start.bat or: python start.py [--rotate 180]"""

import argparse
import atexit
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
SERVE_PY = REPO_ROOT / "shared" / "serve.py"
ADB = Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe"


def kill_ports():
    import socket

    for port in (8765, 8766, 8000):
        try:
            s = socket.socket()
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                # port busy — find and kill via netstat+taskkill
                result = subprocess.run(
                    f'netstat -ano | findstr ":{port} "', shell=True, capture_output=True, text=True
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        subprocess.run(
                            f"taskkill /PID {parts[-1]} /F", shell=True, capture_output=True
                        )
            s.close()
        except Exception:
            pass


def setup_adb():
    if not ADB.exists():
        print("[ADB] adb.exe not found — skipping")
        return
    try:
        r1 = subprocess.run(
            [str(ADB), "reverse", "tcp:8000", "tcp:8000"], capture_output=True, text=True
        )
        r2 = subprocess.run(
            [str(ADB), "reverse", "tcp:8766", "tcp:8766"], capture_output=True, text=True
        )
        if "error" in (r1.stderr + r2.stderr).lower():
            print("[ADB] Phone not detected — USB not connected?")
        else:
            print("[ADB] Ports forwarded: 8000, 8766")
    except Exception as e:
        print(f"[ADB] Error: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Rotate phone camera frame (0/90/180/270)",
    )
    args = p.parse_args()

    os.chdir(HERE)

    print("Stopping old processes...")
    kill_ports()
    time.sleep(0.8)

    # ── shared/serve.py — HTTP сервер (раздаёт весь репо) ────────────────────
    p_serve = subprocess.Popen(
        [sys.executable, str(SERVE_PY), "--open", "/spells/index.html"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # ── ADB ───────────────────────────────────────────────────────────────────
    time.sleep(1)
    setup_adb()

    # ── server.py — WebSocket + детекция ─────────────────────────────────────
    server_cmd = [sys.executable, "server.py", "--phone", "--debug"]
    if args.rotate:
        server_cmd += ["--rotate", str(args.rotate)]
    p_server = subprocess.Popen(server_cmd)

    def cleanup():
        print("\nStopping servers...")
        for proc in (p_server, p_serve):
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    atexit.register(cleanup)

    print()
    print("  Browser : http://localhost:8000/spells/index.html")
    print("  Phone   : http://localhost:8000/shared/phone_camera.html")
    if args.rotate:
        print(f"  Rotate  : {args.rotate}°")
    print()
    print("  Close this window or press Ctrl+C to stop everything.")
    print()

    # ── ADB watchdog: повторно пробрасываем порты каждые 10 сек ─────────────
    def adb_watchdog():
        while True:
            time.sleep(10)
            try:
                setup_adb()
            except Exception:
                pass

    import threading

    threading.Thread(target=adb_watchdog, daemon=True).start()

    try:
        p_server.wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
