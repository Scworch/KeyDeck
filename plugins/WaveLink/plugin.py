import ctypes
from ctypes import wintypes
import os
import queue
import sys
import threading
from pathlib import Path

# Add plugin dir to sys.path
plugin_dir = Path(__file__).resolve().parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

import keyboard
from keydeck.plugin_api import PluginBase, PluginContext
from wavelink_api import WaveLinkClient, WaveLinkError


WH_KEYBOARD_LL = 13
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
    LONG_PTR = ctypes.c_longlong
else:
    ULONG_PTR = ctypes.c_ulong
    LONG_PTR = ctypes.c_long

LRESULT = LONG_PTR


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


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


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.SetWindowsHookExW.argtypes = [
        wintypes.INT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p,
        wintypes.INT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.INT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
else:
    user32 = None
    kernel32 = None
    LowLevelKeyboardProc = None


class Plugin(PluginBase):
    plugin_id = "wavelink_control"
    plugin_name = "Wave Link Control"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context)
        self.client: WaveLinkClient | None = None
        self._hotkeys: list[object] = []
        self._volume_lock = threading.Lock()
        self._volume_events: queue.Queue[bool | None] = queue.Queue()
        self._volume_worker: threading.Thread | None = None
        self._volume_hook_thread: threading.Thread | None = None
        self._volume_hook_stop = threading.Event()
        self._volume_hook_ready = threading.Event()
        self._volume_hook_thread_id = 0
        self._volume_hook = None
        self._volume_hook_callback = (
            LowLevelKeyboardProc(self._low_level_keyboard_proc)
            if LowLevelKeyboardProc is not None
            else None
        )

    def start(self) -> None:
        """Starts low-level keyboard hook listener and connects to Wave Link."""
        channel_name = "Music"
        step = 5

        self.client = WaveLinkClient()

        try:
            self.client.connect()
        except Exception:
            pass

        try:
            # add_hotkey gives exactly one callback per F13/F14 press and avoids
            # matching unrelated keys by scan code.
            self._hotkeys = [
                keyboard.add_hotkey("f13", lambda: self._handle_volume_change(channel_name, step, True)),
                keyboard.add_hotkey("f14", lambda: self._handle_volume_change(channel_name, step, False)),
            ]
        except Exception:
            pass

        self._volume_worker = threading.Thread(
            target=self._volume_worker_loop,
            args=(channel_name, step),
            name="WaveLinkVolumeWorker",
            daemon=True,
        )
        self._volume_worker.start()
        self._start_volume_hook()

    def _volume_worker_loop(self, channel_name: str, step: int) -> None:
        while True:
            increase = self._volume_events.get()
            if increase is None:
                return
            self._handle_volume_change(channel_name, step, increase)

    def _start_volume_hook(self) -> None:
        if os.name != "nt" or self._volume_hook_callback is None:
            return
        self._volume_hook_stop.clear()
        self._volume_hook_ready.clear()
        self._volume_hook_thread = threading.Thread(
            target=self._volume_hook_loop,
            name="WaveLinkVolumeHook",
            daemon=True,
        )
        self._volume_hook_thread.start()
        self._volume_hook_ready.wait(timeout=2.0)

    def _volume_hook_loop(self) -> None:
        if user32 is None or kernel32 is None or self._volume_hook_callback is None:
            return

        self._volume_hook_thread_id = kernel32.GetCurrentThreadId()
        message = MSG()
        user32.PeekMessageW(
            ctypes.byref(message),
            None,
            0,
            0,
            PM_NOREMOVE,
        )
        self._volume_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._volume_hook_callback,
            kernel32.GetModuleHandleW(None),
            0,
        )
        self._volume_hook_ready.set()
        if not self._volume_hook:
            self._volume_hook_thread_id = 0
            return

        while not self._volume_hook_stop.is_set():
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

        user32.UnhookWindowsHookEx(self._volume_hook)
        self._volume_hook = None
        self._volume_hook_thread_id = 0

    def _low_level_keyboard_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0 and w_param in (
            WM_KEYDOWN,
            WM_KEYUP,
            WM_SYSKEYDOWN,
            WM_SYSKEYUP,
        ):
            event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if event.vkCode == VK_VOLUME_UP:
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._volume_events.put(True)
                return 1
            if event.vkCode == VK_VOLUME_DOWN:
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._volume_events.put(False)
                return 1

        if user32 is None:
            return 0
        return user32.CallNextHookEx(self._volume_hook, n_code, w_param, l_param)

    def _handle_volume_change(self, channel_name: str, step: int, increase: bool) -> None:
        if self.client is None:
            self.client = WaveLinkClient()

        try:
            with self._volume_lock:
                if not self.client.is_connected():
                    self.client.connect()
                if increase:
                    self.client.increase_volume(channel_name, step)
                else:
                    self.client.decrease_volume(channel_name, step)
        except WaveLinkError:
            pass
        except Exception:
            pass

    def stop(self) -> None:
        """Stops keyboard hooks and closes Wave Link connection."""
        for hotkey in self._hotkeys:
            try:
                keyboard.remove_hotkey(hotkey)
            except Exception:
                pass
        self._hotkeys = []

        self._volume_hook_stop.set()
        if user32 is not None and self._volume_hook_thread_id:
            user32.PostThreadMessageW(self._volume_hook_thread_id, WM_QUIT, 0, 0)
        if self._volume_hook_thread:
            self._volume_hook_thread.join(timeout=2.0)
            self._volume_hook_thread = None
        self._volume_events.put(None)
        if self._volume_worker:
            self._volume_worker.join(timeout=2.0)
            self._volume_worker = None

        if self.client:
            self.client.disconnect()
            self.client = None

    def actions(self) -> list:
        return []
