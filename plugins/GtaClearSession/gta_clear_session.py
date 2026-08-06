from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass

import psutil

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MUTEX_NAME = "Local\\KeyDeck_GTA_Clear_Session_Running"
WAIT_OBJECT_0 = 0x00000000
ERROR_ALREADY_EXISTS = 183


@dataclass
class ClearSessionSettings:
    action_title: str = "GTA: Clear Session"
    process_names: tuple[str, ...] = ("GTA5_Enhanced.exe", "GTA5.exe")
    suspend_seconds: float = 8.0

    @classmethod
    def from_dict(cls, data: dict) -> "ClearSessionSettings":
        raw_names = data.get("process_names", cls().process_names)
        names: list[str] = []
        if isinstance(raw_names, list):
            for item in raw_names:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
        if not names:
            names = list(cls().process_names)

        raw_seconds = data.get("suspend_seconds", cls().suspend_seconds)
        try:
            suspend_seconds = float(raw_seconds)
        except (TypeError, ValueError):
            suspend_seconds = cls().suspend_seconds

        action_title = str(data.get("action_title", cls().action_title)).strip() or cls().action_title
        return cls(
            action_title=action_title,
            process_names=tuple(names),
            suspend_seconds=max(1.0, min(suspend_seconds, 30.0)),
        )

    def to_dict(self) -> dict:
        return {
            "action_title": self.action_title,
            "process_names": list(self.process_names),
            "suspend_seconds": self.suspend_seconds,
        }


class AlreadyRunningError(RuntimeError):
    pass


class MutexGuard:
    def __init__(self, name: str) -> None:
        self._name = name
        self._handle = None

    def acquire(self) -> None:
        handle = kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            raise RuntimeError("Failed to create mutex")
        self._handle = handle
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            self.release()
            raise AlreadyRunningError("GTA session clear is already running.")

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


def find_gta_process(process_names: tuple[str, ...]) -> psutil.Process:
    wanted = {name.lower() for name in process_names}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if name in wanted:
                return psutil.Process(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, ValueError):
            continue
    raise RuntimeError(f"Process not found: {', '.join(process_names)}")


def focus_process_window(pid: int) -> None:
    hwnds: list[int] = []

    def callback(hwnd, _lparam):
        current_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
        if user32.IsWindowVisible(hwnd) and current_pid.value == pid:
            hwnds.append(hwnd)
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(callback)
    user32.EnumWindows(enum_proc, 0)

    if hwnds:
        hwnd = hwnds[0]
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)


def clear_session(settings: ClearSessionSettings) -> None:
    mutex = MutexGuard(MUTEX_NAME)
    mutex.acquire()
    try:
        proc = find_gta_process(settings.process_names)
        proc.suspend()
        try:
            time.sleep(settings.suspend_seconds)
        finally:
            try:
                proc.resume()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        focus_process_window(proc.pid)
    finally:
        mutex.release()


def run_async(
    settings: ClearSessionSettings,
    on_error,
    on_busy,
) -> None:
    def worker() -> None:
        try:
            clear_session(settings)
        except AlreadyRunningError as exc:
            on_busy(str(exc))
        except Exception as exc:  # noqa: BLE001
            on_error(str(exc))

    thread = threading.Thread(
        target=worker,
        name="keydeck-gta-clear-session",
        daemon=True,
    )
    thread.start()
