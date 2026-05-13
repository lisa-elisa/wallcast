"""Network utilities."""

import socket


def get_local_ip() -> str:
    """Return this machine's LAN IP, or 'localhost' if discovery fails."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"
