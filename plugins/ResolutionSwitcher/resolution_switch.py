from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass


ENUM_CURRENT_SETTINGS = -1

DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
DM_BITSPERPEL = 0x00040000

DISP_CHANGE_SUCCESSFUL = 0
CDS_UPDATEREGISTRY = 0x00000001


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", wintypes.WORD),
        ("dmDuplex", wintypes.WORD),
        ("dmYResolution", wintypes.WORD),
        ("dmTTOption", wintypes.WORD),
        ("dmCollate", wintypes.WORD),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)


@dataclass
class DisplayMode:
    width: int
    height: int
    frequency: int
    bits_per_pixel: int


def _fresh_devmode() -> DEVMODEW:
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    return mode


def current_mode() -> DisplayMode:
    mode = _fresh_devmode()
    ok = user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(mode))
    if not ok:
        raise RuntimeError("Failed to read current display mode")
    return DisplayMode(
        width=int(mode.dmPelsWidth),
        height=int(mode.dmPelsHeight),
        frequency=int(mode.dmDisplayFrequency),
        bits_per_pixel=int(mode.dmBitsPerPel),
    )


def enumerate_modes() -> list[DisplayMode]:
    modes: list[DisplayMode] = []
    i = 0
    while True:
        mode = _fresh_devmode()
        ok = user32.EnumDisplaySettingsW(None, i, ctypes.byref(mode))
        if not ok:
            break
        modes.append(
            DisplayMode(
                width=int(mode.dmPelsWidth),
                height=int(mode.dmPelsHeight),
                frequency=int(mode.dmDisplayFrequency),
                bits_per_pixel=int(mode.dmBitsPerPel),
            )
        )
        i += 1
    return modes


def _choose_target_mode(
    width: int,
    height: int,
    min_frequency: int,
) -> DisplayMode | None:
    candidates = [
        mode
        for mode in enumerate_modes()
        if mode.width == width and mode.height == height and mode.frequency >= min_frequency
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (m.frequency, m.bits_per_pixel), reverse=True)
    return candidates[0]


def apply_mode(mode: DisplayMode) -> None:
    devmode = _fresh_devmode()
    devmode.dmPelsWidth = mode.width
    devmode.dmPelsHeight = mode.height
    devmode.dmDisplayFrequency = mode.frequency
    devmode.dmBitsPerPel = mode.bits_per_pixel
    devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY | DM_BITSPERPEL

    # Persist mode in registry as well; this helps avoid unexpected rollbacks.
    result = user32.ChangeDisplaySettingsExW(None, ctypes.byref(devmode), None, CDS_UPDATEREGISTRY, None)
    if result != DISP_CHANGE_SUCCESSFUL:
        result = user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)
    if result != DISP_CHANGE_SUCCESSFUL:
        raise RuntimeError(f"ChangeDisplaySettings failed with code {result}")


def switch_resolution_keep_frequency(width: int, height: int) -> DisplayMode:
    current = current_mode()
    target = _choose_target_mode(width=width, height=height, min_frequency=current.frequency)
    if target is None:
        raise RuntimeError(
            f"No display mode {width}x{height} with refresh >= {current.frequency}Hz is available"
        )
    apply_mode(target)
    time.sleep(0.12)
    applied = current_mode()
    if (
        applied.width != target.width
        or applied.height != target.height
        or applied.frequency < current.frequency
    ):
        apply_mode(target)
        time.sleep(0.12)
        applied = current_mode()
        if (
            applied.width != target.width
            or applied.height != target.height
            or applied.frequency < current.frequency
        ):
            raise RuntimeError(
                "Target mode did not stick (possible driver/game override)."
            )
    return target
