"""Paths shared by source runs and the installed Windows application."""
from pathlib import Path
import os
import sys


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def default_data_dir(demo: bool = False) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "PostureTrack"
        return base / ("demo" if demo else "data")
    return resource_root() / ".data" / ("demo" if demo else "local")


_mutex = None


def acquire_instance() -> bool:
    """Keep a per-session mutex alive until process exit; never steal a camera."""
    global _mutex
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    _mutex = kernel.CreateMutexW(None, False, "Local\\PostureTrack.Application")
    if not _mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle(_mutex)
        _mutex = None
        return False
    return True
