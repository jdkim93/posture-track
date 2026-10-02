"""Block Python network connections before loading inference dependencies.

Native DLL behavior still requires release-time network observation. This is
defense in depth, not a substitute for an OS firewall or native binary audit.
"""
import os
import socket
from pathlib import Path


def enforce_local_only() -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    cache = Path(__file__).resolve().parent.parent / ".data" / "runtime-cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache)

    def blocked(*args, **kwargs):
        raise PermissionError("Posture Track: external network connections are disabled")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
