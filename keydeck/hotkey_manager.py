from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import keyboard
from PySide6.QtCore import QObject, Qt, Signal

logger = logging.getLogger(__name__)


class _WindowsRightAltHook:
    """Intercepts Right Alt before keyboard's Windows AltGr translation."""

    _WH_KEYBOARD_LL = 13
    _WM_KEYDOWN = 0x0100
    _WM_KEYUP = 0x0101
    _WM_SYSKEYDOWN = 0x0104
    _WM_SYSKEYUP = 0x0105
    _VK_LCONTROL = 0xA2
    _VK_RMENU = 0xA5
    _LLKHF_INJECTED = 0x10
    _REPLAY_DELAY = 0.08

    def __init__(self, callback: Callable[[], None]) -> None:
        import ctypes
        from ctypes import wintypes

        if not hasattr(ctypes, "windll"):
            raise OSError("Right Alt interception is only supported on Windows")

        self._ctypes = ctypes
        self._callback = callback
        self._lock = threading.RLock()
        self._pending_ctrl_scan: int | None = None
        self._pending_ctrl_time = 0.0
        self._pending_ctrl_timer: threading.Timer | None = None
        self._suppressed_ctrl_scan: int | None = None
        self._right_alt_down = False
        self._right_alt_time = 0.0
        self._replay_marker = id(self) & ((1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        self._event_type = KBDLLHOOKSTRUCT
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        self._user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            self._hook_proc_type,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self._user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self._user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self._user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        self._user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self._user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        self._proc = self._hook_proc_type(self._handle_event)
        self._hook = self._user32.SetWindowsHookExW(
            self._WH_KEYBOARD_LL,
            self._proc,
            self._kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            raise ctypes.WinError()

    def _handle_event(self, code: int, message: int, event_ptr: int) -> int:
        if code < 0:
            return self._user32.CallNextHookEx(self._hook, code, message, event_ptr)

        event = self._ctypes.cast(
            self._ctypes.c_void_p(event_ptr),
            self._ctypes.POINTER(self._event_type),
        ).contents
        if event.dwExtraInfo == self._replay_marker:
            return self._user32.CallNextHookEx(self._hook, code, message, event_ptr)

        is_down = message in (self._WM_KEYDOWN, self._WM_SYSKEYDOWN)
        is_up = message in (self._WM_KEYUP, self._WM_SYSKEYUP)

        if event.vkCode == self._VK_RMENU:
            with self._lock:
                if is_down:
                    if self._pending_ctrl_scan is not None:
                        if time.monotonic() - self._pending_ctrl_time <= self._REPLAY_DELAY:
                            self._suppressed_ctrl_scan = self._pending_ctrl_scan
                            self._clear_pending_ctrl()
                        else:
                            self._replay_pending_ctrl()
                    if not self._right_alt_down:
                        self._right_alt_down = True
                        self._right_alt_time = time.monotonic()
                        self._callback()
                elif is_up:
                    self._right_alt_down = False
                    self._right_alt_time = time.monotonic()
            return 1

        if (
            event.vkCode == self._VK_LCONTROL
            and event.flags & self._LLKHF_INJECTED
        ):
            with self._lock:
                if is_down:
                    if self._suppressed_ctrl_scan == event.scanCode:
                        return 1
                    if (
                        self._right_alt_down
                        or time.monotonic() - self._right_alt_time <= self._REPLAY_DELAY
                    ):
                        self._suppressed_ctrl_scan = event.scanCode
                        return 1
                    if self._pending_ctrl_scan == event.scanCode:
                        return 1
                    self._replay_pending_ctrl()
                    self._pending_ctrl_scan = event.scanCode
                    self._pending_ctrl_time = time.monotonic()
                    self._pending_ctrl_timer = threading.Timer(
                        self._REPLAY_DELAY,
                        self._replay_pending_ctrl,
                    )
                    self._pending_ctrl_timer.daemon = True
                    self._pending_ctrl_timer.start()
                    return 1
                if is_up and self._pending_ctrl_scan is not None:
                    self._replay_pending_ctrl()
                elif is_up and self._suppressed_ctrl_scan == event.scanCode:
                    self._suppressed_ctrl_scan = None
                    self._right_alt_time = 0.0
                    return 1

        elif self._pending_ctrl_scan is not None:
            with self._lock:
                self._replay_pending_ctrl()

        return self._user32.CallNextHookEx(self._hook, code, message, event_ptr)

    def _clear_pending_ctrl(self) -> None:
        if self._pending_ctrl_timer is not None:
            self._pending_ctrl_timer.cancel()
            self._pending_ctrl_timer = None
        self._pending_ctrl_scan = None

    def _replay_pending_ctrl(self) -> None:
        with self._lock:
            if self._pending_ctrl_scan is None:
                return
            scan_code = self._pending_ctrl_scan
            self._clear_pending_ctrl()
            self._user32.keybd_event(
                self._VK_LCONTROL,
                scan_code,
                0,
                self._replay_marker,
            )

    def stop(self) -> None:
        with self._lock:
            self._replay_pending_ctrl()
            if self._hook:
                self._user32.UnhookWindowsHookEx(self._hook)
                self._hook = None


class HotkeySignal(QObject):
    triggered = Signal(str)
    toggle_requested = Signal()


class HotkeyManager:
    """Manages global hotkeys using the keyboard module."""

    def __init__(
        self,
        callback: Callable[[str], None],
        toggle_callback: Callable[[], None],
    ) -> None:
        self._callback = callback
        self._toggle_callback = toggle_callback
        self._signal = HotkeySignal()
        self._signal.triggered.connect(self._on_triggered)
        self._signal.toggle_requested.connect(
            self._toggle_callback,
            Qt.ConnectionType.QueuedConnection,
        )
        self._hotkey_handles: list[object] = []
        self._right_alt_hook: _WindowsRightAltHook | None = None

    def _on_triggered(self, slot_key: str) -> None:
        self._callback(slot_key)

    def _trigger_slot(self, slot_key: str) -> None:
        self._signal.triggered.emit(slot_key)

    def apply_hotkeys(
        self,
        slot_hotkeys: dict[str, str],
        right_alt_toggle: bool = False,
    ) -> None:
        """Applies a new set of hotkeys, unregistering old ones."""
        for handle in self._hotkey_handles:
            keyboard.unhook(handle)
        self._hotkey_handles.clear()
        if self._right_alt_hook is not None:
            self._right_alt_hook.stop()
            self._right_alt_hook = None

        for slot_str, key_combo in slot_hotkeys.items():
            if not key_combo:
                continue
            try:
                handle = keyboard.add_hotkey(
                    key_combo, lambda key=slot_str: self._trigger_slot(key), suppress=True
                )
                self._hotkey_handles.append(handle)
            except Exception as e:
                logger.error(f"Failed to bind hotkey '{key_combo}' for slot {slot_str}: {e}")

        if right_alt_toggle:
            try:
                self._right_alt_hook = _WindowsRightAltHook(
                    self._signal.toggle_requested.emit,
                )
            except Exception as e:
                logger.exception(f"Failed to bind Right Alt toggle hotkey: {e}")

    def stop(self) -> None:
        for handle in self._hotkey_handles:
            keyboard.unhook(handle)
        self._hotkey_handles.clear()
        if self._right_alt_hook is not None:
            self._right_alt_hook.stop()
            self._right_alt_hook = None
