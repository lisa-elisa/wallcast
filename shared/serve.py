"""
HTTP server for the browser display + phone camera page.

Serves the entire repository root on 0.0.0.0 so phones on the same WiFi
can access it. From the root you can navigate to either AR mode:

  http://localhost:8000/                          -> landing page
  http://localhost:8000/falling_balls/index.html  -> falling balls display
  http://localhost:8000/spells/index.html    -> spells display
  http://<IP>:8000/shared/phone_camera.html       -> phone camera (both modes)

Usage:
  python shared/serve.py
  python shared/serve.py --open /falling_balls/index.html
  python shared/serve.py --open /spells/index.html
"""

import argparse
import http.server
import os
import socket
import socketserver
import threading
import webbrowser
from pathlib import Path

PORT = 8000
REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--open",
        dest="open_path",
        default="/",
        help="Path to open in the browser (default: landing page at /)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open a browser window",
    )
    args = parser.parse_args()

    local_ip = get_local_ip()

    handler = http.server.SimpleHTTPRequestHandler
    handler.extensions_map.update({".js": "application/javascript"})
    handler.log_message = lambda *a: None

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), handler) as httpd:
        print(f"\n  Landing page      : http://localhost:{PORT}/")
        print(f"  Falling Balls     : http://localhost:{PORT}/falling_balls/index.html")
        print(f"  Spells       : http://localhost:{PORT}/spells/index.html")
        print(f"  Phone camera page : http://{local_ip}:{PORT}/shared/phone_camera.html")
        print("\n  Open the phone camera URL on your phone (same WiFi).")
        print("  Press Ctrl+C to stop.\n")

        if not args.no_browser:
            url = f"http://localhost:{PORT}{args.open_path}"
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
