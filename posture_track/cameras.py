"""Enumerate Windows DirectShow cameras in the same order as CAP_DSHOW."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import uuid


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str


def connected_cameras():
    # Enumerate device monikers rather than opening every possible camera index.
    # This works while the selected camera is already in use by our worker.
    ole = ctypes.OleDLL('ole32')
    automation = ctypes.OleDLL('oleaut32')
    class Guid(ctypes.Structure):
        _fields_ = [('data', ctypes.c_ubyte * 16)]
        def __init__(self, value):
            super().__init__()
            self.data[:] = uuid.UUID(value).bytes_le
    class VariantValue(ctypes.Union):
        _fields_ = [('pointer', ctypes.c_void_p), ('record', ctypes.c_void_p * 2),
                    ('integer', ctypes.c_int64)]
    class Variant(ctypes.Structure):
        _fields_ = [('vt', ctypes.c_ushort), ('reserved', ctypes.c_ushort * 3),
                    ('value', VariantValue)]

    def call(pointer, method, types, *args):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        function = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[method])
        return function(pointer, *args)
    def release(pointer):
        if pointer:
            call(pointer, 2, ())
    def check(code):
        if code < 0:
            raise OSError(f'카메라 목록을 읽을 수 없습니다 (0x{code & 0xffffffff:08X})')

    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(Guid), ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    automation.VariantClear.argtypes = [ctypes.POINTER(Variant)]
    automation.VariantClear.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    # An already initialized multithreaded COM apartment is also usable.
    if initialized < 0 and initialized != -2147417850:
        check(initialized)
    dev_enum = ctypes.c_void_p()
    monikers = ctypes.c_void_p()
    devices = []
    try:
        check(ole.CoCreateInstance(ctypes.byref(Guid('62be5d10-60eb-11d0-bd3b-00a0c911ce86')),
                                  None, 1, ctypes.byref(Guid('29840822-5b84-11d0-bd3b-00a0c911ce86')),
                                  ctypes.byref(dev_enum)))
        result = call(dev_enum, 3, (ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong),
                      ctypes.byref(Guid('860bb310-5d01-11d0-bd3b-00a0c911ce86')), ctypes.byref(monikers), 0)
        check(result)
        if result == 1 or not monikers:
            return []
        while True:
            moniker = ctypes.c_void_p()
            fetched = ctypes.c_ulong()
            result = call(monikers, 3, (ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_ulong)),
                          1, ctypes.byref(moniker), ctypes.byref(fetched))
            check(result)
            if result == 1 or fetched.value == 0:
                break
            bag = ctypes.c_void_p()
            name = '카메라'
            try:
                result = call(moniker, 9, (ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)),
                              None, None, ctypes.byref(Guid('55272a00-42cb-11ce-8135-00aa004bb851')), ctypes.byref(bag))
                if result >= 0 and bag:
                    value = Variant()
                    try:
                        result = call(bag, 3, (ctypes.c_wchar_p, ctypes.POINTER(Variant), ctypes.c_void_p),
                                      'FriendlyName', ctypes.byref(value), None)
                        if result >= 0 and value.vt == 8 and value.value.pointer:
                            name = ctypes.wstring_at(value.value.pointer)
                    finally:
                        automation.VariantClear(ctypes.byref(value))
                devices.append(CameraDevice(len(devices), name))
            finally:
                release(bag)
                release(moniker)
        return devices
    finally:
        release(monikers)
        release(dev_enum)
        if initialized >= 0:
            ole.CoUninitialize()
