from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import tempfile


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Windows DPAPI is required to store Discord credentials")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(_DataBlob)
    if protect:
        crypt32.CryptProtectData.argtypes = [
            blob_pointer,
            ctypes.c_wchar_p,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        crypt32.CryptProtectData.restype = ctypes.c_int
    else:
        crypt32.CryptUnprotectData.argtypes = [
            blob_pointer,
            ctypes.POINTER(ctypes.c_wchar_p),
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    flags = 0x1
    if protect:
        success = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    else:
        success = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class SecureCredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        try:
            protected = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        raw = _dpapi_transform(protected, protect=False)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Stored Discord credentials have an invalid format")
        return value

    def save(self, credentials: dict) -> None:
        raw = json.dumps(credentials, ensure_ascii=True).encode("utf-8")
        protected = _dpapi_transform(raw, protect=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                output.write(protected)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
