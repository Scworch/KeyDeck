import ctypes
import logging
import os
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_SHOW = 0x8002
OBJID_WINDOW = 0
CHILDID_SELF = 0
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
GA_ROOT = 2
SW_HIDE = 0

WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
WinEventProc = WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    ctypes.c_long,
    ctypes.c_long,
    wintypes.DWORD,
    wintypes.DWORD,
)


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class VolumeOsdHider:
    def __init__(self) -> None:
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._callback = WinEventProc(self._on_event)
        self._startup_error: Exception | None = None

    def start(self) -> None:
        if os.name != "nt":
            raise OSError("Volume OSD hiding is only supported on Windows")
        if self._thread and self._thread.is_alive():
            return

        self._ready.clear()
        self._stop.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run,
            name="WaveLinkVolumeOsdHider",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            self.stop()
            raise TimeoutError("Timed out while starting the Volume OSD watcher")
        if self._startup_error is not None:
            raise RuntimeError("Could not start the Volume OSD watcher") from self._startup_error

    def stop(self) -> None:
        self._stop.set()
        if os.name == "nt" and self._thread_id:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostThreadMessageW(
                self._thread_id,
                WM_QUIT,
                0,
                0,
            )
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                logger.error("Volume OSD watcher did not stop in time")
        self._thread = None

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetWinEventHook.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HMODULE,
            WinEventProc,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        user32.UnhookWinEvent.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._thread_id = kernel32.GetCurrentThreadId()
        message = MSG()
        user32.PeekMessageW(
            ctypes.byref(message),
            None,
            0,
            0,
            PM_NOREMOVE,
        )
        self._hook = user32.SetWinEventHook(
            EVENT_OBJECT_CREATE,
            EVENT_OBJECT_SHOW,
            None,
            self._callback,
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
        if not self._hook:
            self._startup_error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            self._thread_id = 0
            return

        self._ready.set()
        try:
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hook:
                user32.UnhookWinEvent(self._hook)
                self._hook = None
            self._thread_id = 0

    def _on_event(
        self,
        hook,
        event,
        hwnd,
        object_id,
        child_id,
        event_thread,
        event_time,
    ) -> None:
        if (
            event not in (EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW)
            or object_id != OBJID_WINDOW
            or child_id != CHILDID_SELF
            or not hwnd
        ):
            return

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.FindWindowExW.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
            ]
            user32.FindWindowExW.restype = wintypes.HWND
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.GetClassNameW.argtypes = [
                wintypes.HWND,
                wintypes.LPWSTR,
                ctypes.c_int,
            ]
            user32.GetClassNameW.restype = ctypes.c_int

            root = user32.GetAncestor(hwnd, GA_ROOT)
            if not root or not self._is_volume_osd(root, user32):
                return
            user32.ShowWindow(root, SW_HIDE)
            logger.debug("Hid Windows Volume OSD window (event 0x%X)", event)
        except Exception:
            logger.exception("Could not hide the Windows Volume OSD window")

    @staticmethod
    def _class_name(hwnd, user32) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        length = user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value if length else ""

    @classmethod
    def _is_volume_osd(cls, hwnd, user32) -> bool:
        outer_class = cls._class_name(hwnd, user32)
        if outer_class == "NativeHWNDHost":
            return bool(
                user32.FindWindowExW(hwnd, None, "DirectUIHWND", "")
            )
        if outer_class == "XamlExplorerHostIslandWindow":
            return bool(
                user32.FindWindowExW(
                    hwnd,
                    None,
                    "Windows.UI.Composition.DesktopWindowContentBridge",
                    "DesktopWindowXamlSource",
                )
            )
        return False
