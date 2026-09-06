from __future__ import annotations

import ctypes
import os
from typing import Any

VALUE_NAME = "_User_Global_VAL_SuperResolution"
MODE_TO_VALUE = {"off": 0, "1": 1, "2": 2, "3": 3, "4": 4, "auto": 5}
VALUE_TO_MODE = {value: mode for mode, value in MODE_TO_VALUE.items()}
NVCPL_SETTING_VSR_VALUE = 0x317
NVCPL_COMMIT = 0x00010000


def _nvcpl_value() -> int:
    if os.name != "nt":
        raise RuntimeError("NVIDIA VSR control is only supported on Windows")

    dll_path = (
        os.environ.get("ProgramFiles", r"C:\Program Files")
        + r"\NVIDIA Corporation\NVIDIA App\NvCpl\NvCpl.dll"
    )
    try:
        dll = ctypes.WinDLL(dll_path)
    except OSError as exc:
        raise RuntimeError(f"Cannot load NVIDIA NvCpl API: {exc}") from exc

    is_running = dll.NvCplApiIsUxdServiceRunning
    is_running.argtypes = [ctypes.POINTER(ctypes.c_bool)]
    is_running.restype = ctypes.c_int32
    running = ctypes.c_bool()
    if is_running(ctypes.byref(running)) != 0 or not running.value:
        raise RuntimeError("NVIDIA UXD service is not available")

    init = dll.NvCplApiInit
    init.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    init.restype = ctypes.c_int32
    status = init(None, None)
    if status != 0:
        raise RuntimeError(f"NvCplApiInit failed with status {status}")

    get_setting = dll.NvCplApiGetSetting
    get_setting.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    get_setting.restype = ctypes.c_int32
    selector = ctypes.c_uint64(0)
    value = ctypes.c_uint32()
    status = get_setting(
        1,
        ctypes.byref(selector),
        NVCPL_SETTING_VSR_VALUE,
        ctypes.byref(value),
        ctypes.sizeof(value),
    )
    if status != 0:
        raise RuntimeError(f"NvCplApiGetSetting(VSR) failed with status {status}")
    return int(value.value)


def read_vsr() -> dict[str, Any]:
    value = _nvcpl_value()
    return {
        "source": "NvCplApiGetSetting",
        "value": {"value": value, "type": 4},
        "mode": VALUE_TO_MODE.get(value),
    }


def set_vsr(mode: str) -> dict[str, Any]:
    if mode not in MODE_TO_VALUE:
        raise ValueError(f"Unsupported VSR mode: {mode}")
    if os.name != "nt":
        raise RuntimeError("NVIDIA VSR control is only supported on Windows")

    dll_path = (
        os.environ.get("ProgramFiles", r"C:\Program Files")
        + r"\NVIDIA Corporation\NVIDIA App\NvCpl\NvCpl.dll"
    )
    try:
        dll = ctypes.WinDLL(dll_path)
    except OSError as exc:
        raise RuntimeError(f"Cannot load NVIDIA NvCpl API: {exc}") from exc

    init = dll.NvCplApiInit
    init.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    init.restype = ctypes.c_int32
    if init(None, None) != 0:
        raise RuntimeError("NvCplApiInit failed")

    set_setting = dll.NvCplApiSetSetting
    set_setting.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    set_setting.restype = ctypes.c_int32
    selector = ctypes.c_uint64(0)
    value = ctypes.c_uint32(MODE_TO_VALUE[mode])
    status = set_setting(
        1,
        ctypes.byref(selector),
        NVCPL_SETTING_VSR_VALUE,
        ctypes.byref(value),
        ctypes.sizeof(value),
    )
    if status != 0:
        raise RuntimeError(f"NvCplApiSetSetting(VSR) failed with status {status}")

    execute = dll.NvCplApiExecute
    execute.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32]
    execute.restype = ctypes.c_int32
    status = execute(NVCPL_COMMIT, 0, -1)
    if status != 0:
        raise RuntimeError(f"NvCplApiExecute(CommitState) failed with status {status}")

    actual = _nvcpl_value()
    if actual != MODE_TO_VALUE[mode]:
        raise RuntimeError(
            f"NVIDIA VSR readback mismatch: requested {MODE_TO_VALUE[mode]}, got {actual}"
        )
    return {"source": "NvCplApiSetSetting + NvCplApiExecute", "value": actual, "mode": mode}
