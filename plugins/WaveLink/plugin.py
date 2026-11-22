import ctypes
from ctypes import wintypes
import logging
import os
import queue
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# Add plugin dir to sys.path
plugin_dir = Path(__file__).resolve().parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from keydeck.plugin_api import PluginBase, PluginContext
from wavelink_api import WaveLinkClient, WaveLinkError


WH_KEYBOARD_LL = 13
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_F13 = 0x7C
VK_F14 = 0x7D
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

logger = logging.getLogger(__name__)

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


def _key_label(vk_code: int) -> str:
    known_names = {
        VK_VOLUME_DOWN: "Volume Down",
        VK_VOLUME_UP: "Volume Up",
        VK_F13: "F13",
        VK_F14: "F14",
        0x08: "Backspace",
        0x09: "Tab",
        0x0D: "Enter",
        0x1B: "Escape",
        0x20: "Space",
        0x25: "Left",
        0x26: "Up",
        0x27: "Right",
        0x28: "Down",
        0x2D: "Insert",
        0x2E: "Delete",
    }
    if vk_code in known_names:
        return known_names[vk_code]
    if 0x30 <= vk_code <= 0x39 or 0x41 <= vk_code <= 0x5A:
        return chr(vk_code)
    if 0x70 <= vk_code <= 0x87:
        return f"F{vk_code - 0x6F}"
    return f"VK 0x{vk_code:02X}"


class WheelCalibrationDialog(QDialog):
    def __init__(self, plugin: "Plugin", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.vk_increase: int | None = None
        self.vk_decrease: int | None = None
        self._waiting_for = "down"

        self.setWindowTitle("Калибровка колёсика громкости")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setStyleSheet(
            """
            QDialog { background-color: #121214; color: #f4f4f5; }
            QLabel { background-color: transparent; color: #f4f4f5; }
            QPushButton { background-color: #27272a; color: #f4f4f5; border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #3f3f46; }
            """
        )

        layout = QVBoxLayout(self)
        self.instructions = QLabel(
            "Поверните колесо наушников вниз.\n"
            "Если системная громкость меняется, но это окно не реагирует, устройство не передаёт "
            "клавиатурное событие. Эта калибровка проверяет только клавиши; для HID-перехвата "
            "нужен отдельный фильтр-драйвер.",
            self,
        )
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.plugin.begin_capture("calibration")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._read_capture)
        self.timer.start(40)
        self.capture_timeout = QTimer(self)
        self.capture_timeout.setSingleShot(True)
        self.capture_timeout.setInterval(8000)
        self.capture_timeout.timeout.connect(self._show_capture_timeout)
        self.capture_timeout.start()

    def _show_capture_timeout(self) -> None:
        self.instructions.setText(
            "Событие от колеса не получено. Возможно, наушники меняют системную громкость напрямую, "
            "не отправляя клавиатурную клавишу. HID-отчёт этой калибровкой не перехватывается."
        )

    def _read_capture(self) -> None:
        vk_code = self.plugin.pop_capture_event()
        if vk_code is None:
            return
        self.capture_timeout.start()

        if self._waiting_for == "down":
            self.vk_decrease = vk_code
            self._waiting_for = "up"
            self.instructions.setText(
                f"Событие при повороте вниз: {_key_label(vk_code)}.\n"
                "Теперь поверните колесо наушников вверх."
            )
            return

        if vk_code == self.vk_decrease:
            self.instructions.setText(
                f"В обоих направлениях получена клавиша {_key_label(vk_code)}.\n"
                "Поверните колесо вверх ещё раз; для направлений нужны разные события."
            )
            return

        self.vk_increase = vk_code
        self.instructions.setText(
            f"Вниз: {_key_label(self.vk_decrease)}; вверх: {_key_label(vk_code)}."
        )
        self.timer.stop()
        self.capture_timeout.stop()
        self.accept()

    def done(self, result: int) -> None:
        if hasattr(self, "capture_timeout"):
            self.capture_timeout.stop()
        self.plugin.end_capture()
        super().done(result)


class KeyboardDiagnosticsDialog(QDialog):
    def __init__(self, plugin: "Plugin", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self._displayed_events = 0

        self.setWindowTitle("Проверка клавиш")
        self.setModal(True)
        self.setMinimumSize(620, 360)
        self.setStyleSheet(
            """
            QDialog { background-color: #121214; color: #f4f4f5; }
            QLabel { background-color: transparent; color: #f4f4f5; }
            QListWidget {
                background-color: #18181b; color: #f4f4f5;
                border: 1px solid #3f3f46; border-radius: 6px;
            }
            QPushButton {
                background-color: #27272a; color: #f4f4f5;
                border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px;
            }
            QPushButton:hover { background-color: #3f3f46; }
            """
        )

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Нажимайте любые клавиши или колесо наушников. Здесь отображаются нажатия и отпускания, "
            "видимые клавиатурному hook Windows. Диагностика не блокирует клавиши и временно "
            "приостанавливает управление громкостью Wave Link.\n"
            "Если системная громкость меняется, но событие здесь не появляется, устройство, "
            "вероятно, передаёт HID- или аудиособытие, а не клавиатурную клавишу.",
            self,
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.event_list = QListWidget(self)
        layout.addWidget(self.event_list)

        self.status = QLabel("Ожидание событий…", self)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        clear_button = buttons.addButton("Очистить", QDialogButtonBox.ActionRole)
        clear_button.clicked.connect(self._clear_events)
        layout.addWidget(buttons)

        self.plugin.begin_capture("diagnostics")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._read_events)
        self._timer.start(30)

    def _read_events(self) -> None:
        events, dropped_count = self.plugin.pop_diagnostic_events()
        for vk_code, message, scan_code, flags, _event_time in events:
            event_name = "Нажатие" if message in (WM_KEYDOWN, WM_SYSKEYDOWN) else "Отпускание"
            injected = " | синтезировано программно" if flags & 0x10 else ""
            self.event_list.addItem(
                f"{event_name}: {_key_label(vk_code)} "
                f"(VK 0x{vk_code:02X}, scan 0x{scan_code:02X}, flags 0x{flags:02X}{injected})"
            )
            self._displayed_events += 1

        while self.event_list.count() > 300:
            self.event_list.takeItem(0)

        if self._displayed_events or dropped_count:
            self.status.setText(
                f"Событий показано: {self._displayed_events}; "
                f"пропущено из-за высокой частоты: {dropped_count}"
            )
        else:
            self.status.setText("Ожидание событий…")

    def _clear_events(self) -> None:
        self.event_list.clear()
        self._displayed_events = 0
        self.plugin.clear_diagnostic_events()
        self.status.setText("Ожидание событий…")

    def done(self, result: int) -> None:
        if hasattr(self, "_timer"):
            self._timer.stop()
        self.plugin.end_capture()
        super().done(result)


class WaveLinkSettingsDialog(QDialog):
    def __init__(
        self,
        plugin: "Plugin",
        channels: list[str],
        channels_error: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self._hotkeys = {
            "increase": plugin.vk_increase,
            "decrease": plugin.vk_decrease,
        }

        self.setWindowTitle("Настройки управления Wave Link")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(
            """
            QDialog { background-color: #121214; color: #f4f4f5; }
            QLabel { background-color: transparent; color: #f4f4f5; }
            QComboBox, QSpinBox {
                background-color: #18181b; color: #f4f4f5;
                border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #18181b; color: #f4f4f5;
                selection-background-color: #2563eb; border: 1px solid #3f3f46;
            }
            QPushButton {
                background-color: #27272a; color: #f4f4f5;
                border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px;
            }
            QPushButton:hover { background-color: #3f3f46; }
            QCheckBox { spacing: 8px; }
            """
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.channel_combo = QComboBox(self)
        self.channel_combo.setEditable(False)
        self.channel_combo.addItems(channels)
        self.channel_combo.setCurrentText(plugin.channel_name)
        form.addRow("Канал Wave Link", self.channel_combo)

        self.channel_status = QLabel(
            channels_error or "Список каналов получен из Wave Link.",
            self,
        )
        self.channel_status.setWordWrap(True)
        if channels_error:
            self.channel_status.setStyleSheet("color: #e6a23c;")
        form.addRow("", self.channel_status)

        self.step_spin = QSpinBox(self)
        self.step_spin.setRange(1, 100)
        self.step_spin.setValue(plugin.step)
        form.addRow("Шаг изменения громкости (%)", self.step_spin)

        self.increase_button = QPushButton(self)
        self.decrease_button = QPushButton(self)
        self._refresh_hotkey_buttons()
        self.increase_button.clicked.connect(lambda: self._start_hotkey_capture("increase"))
        self.decrease_button.clicked.connect(lambda: self._start_hotkey_capture("decrease"))
        form.addRow("Клавиша увеличения громкости", self.increase_button)
        form.addRow("Клавиша уменьшения громкости", self.decrease_button)

        self.calibrate_button = QPushButton("Откалибровать колесо наушников…", self)
        self.calibrate_button.clicked.connect(self._calibrate_wheel)
        form.addRow("", self.calibrate_button)

        self.diagnostics_button = QPushButton("Проверить все клавиши…", self)
        self.diagnostics_button.clicked.connect(self._check_all_keys)
        form.addRow("", self.diagnostics_button)

        self.debug_check = QCheckBox(
            "Вести журнал событий и ошибок (режим отладки)",
            self,
        )
        self.debug_check.setToolTip(
            "Записывает только события управления Wave Link в файл wavelink-debug.log; остальные клавиши не журналируются."
        )
        self.debug_check.setChecked(plugin.debug_mode)
        form.addRow("", self.debug_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._read_hotkey_capture)
        self._capture_timer.start(40)

    def get_settings(self) -> dict:
        return {
            "channel_name": self.channel_combo.currentText().strip(),
            "step": self.step_spin.value(),
            "vk_increase": self._hotkeys["increase"],
            "vk_decrease": self._hotkeys["decrease"],
            "debug_mode": self.debug_check.isChecked(),
        }

    def accept(self) -> None:
        if not self.channel_combo.currentText().strip():
            QMessageBox.warning(self, "Управление Wave Link", "Выберите канал Wave Link.")
            return
        if self._hotkeys["increase"] == self._hotkeys["decrease"]:
            QMessageBox.warning(
                self,
                "Управление Wave Link",
                "Для увеличения и уменьшения громкости нужны разные клавиши.",
            )
            return
        self.plugin.end_capture()
        self._capture_timer.stop()
        super().accept()

    def done(self, result: int) -> None:
        self.plugin.end_capture()
        self._capture_timer.stop()
        super().done(result)

    def _refresh_hotkey_buttons(self) -> None:
        self.increase_button.setText(_key_label(self._hotkeys["increase"]))
        self.decrease_button.setText(_key_label(self._hotkeys["decrease"]))

    def _start_hotkey_capture(self, direction: str) -> None:
        if not self.plugin.volume_hook_active:
            QMessageBox.warning(
                self,
                "Управление Wave Link",
                "Не удалось запустить перехват клавиатуры. Перезапустите KeyDeck и попробуйте снова.",
            )
            return
        self.plugin.begin_capture(f"hotkey:{direction}")
        button = self.increase_button if direction == "increase" else self.decrease_button
        button.setText("Нажмите клавишу…")

    def _read_hotkey_capture(self) -> None:
        mode = self.plugin.capture_mode
        if not mode or not mode.startswith("hotkey:"):
            return
        vk_code = self.plugin.pop_capture_event()
        if vk_code is None:
            return
        direction = mode.split(":", 1)[1]
        other_direction = "decrease" if direction == "increase" else "increase"
        if vk_code == self._hotkeys[other_direction]:
            QMessageBox.warning(
                self,
                "Управление Wave Link",
                "Для увеличения и уменьшения громкости нужны разные клавиши.",
            )
            self.plugin.end_capture()
            self._refresh_hotkey_buttons()
            return
        self._hotkeys[direction] = vk_code
        self.plugin.end_capture()
        self._refresh_hotkey_buttons()

    def _check_all_keys(self) -> None:
        if not self.plugin.volume_hook_active:
            QMessageBox.warning(
                self,
                "Управление Wave Link",
                "Не удалось запустить перехват клавиатуры. Перезапустите KeyDeck и попробуйте снова.",
            )
            return
        dialog = KeyboardDiagnosticsDialog(self.plugin, self)
        dialog.exec()

    def _calibrate_wheel(self) -> None:
        if not self.plugin.volume_hook_active:
            QMessageBox.warning(
                self,
                "Управление Wave Link",
                "Перехват клавиатуры не запущен. Перезапустите KeyDeck перед настройкой.",
            )
            return
        dialog = WheelCalibrationDialog(self.plugin, self)
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.vk_increase is None or dialog.vk_decrease is None:
            return
        self._hotkeys["increase"] = dialog.vk_increase
        self._hotkeys["decrease"] = dialog.vk_decrease
        self._refresh_hotkey_buttons()


class Plugin(PluginBase):
    plugin_id = "wavelink_control"
    plugin_name = "Управление Wave Link"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context)
        self.client: WaveLinkClient | None = None
        self._volume_lock = threading.Lock()
        self._volume_events: queue.Queue[bool | None] = queue.Queue()
        self._capture_events: queue.Queue[int] = queue.Queue()
        self._diagnostic_events: queue.Queue[tuple[int, int, int, int, int]] = queue.Queue(
            maxsize=1024
        )
        self._state_lock = threading.Lock()
        self._capture_mode: str | None = None
        self._diagnostic_dropped_events = 0
        self._pressed_keys: set[int] = set()
        self._pressed_at: dict[int, int] = {}
        self._captured_keys: set[int] = set()
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
        self._volume_hook_active = False
        self._debug_handler: logging.FileHandler | None = None
        self._debug_previous_level: int | None = None
        self.channel_name = "Music"
        self.step = 5
        self.vk_increase = VK_F13
        self.vk_decrease = VK_F14
        self.hotkey_increase = "f13"
        self.hotkey_decrease = "f14"
        self.debug_mode = False
        self._load_settings()
        self._configure_debug_logging()

    def start(self) -> None:
        """Starts low-level keyboard hook listener and connects to Wave Link."""
        if self._volume_worker and self._volume_worker.is_alive():
            return

        self.client = WaveLinkClient()

        try:
            self.client.connect()
        except WaveLinkError:
            logger.exception("Could not connect to Wave Link on startup")

        self._volume_worker = threading.Thread(
            target=self._volume_worker_loop,
            name="WaveLinkVolumeWorker",
            daemon=True,
        )
        self._volume_worker.start()
        self._start_volume_hook()

    def _volume_worker_loop(self) -> None:
        while True:
            increase = self._volume_events.get()
            if increase is None:
                return
            with self._state_lock:
                channel_name = self.channel_name
                step = self.step
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
        self._volume_hook_active = bool(self._volume_hook)
        if not self._volume_hook_active:
            logger.error("Could not install Wave Link keyboard hook (Windows error %s)", ctypes.get_last_error())

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
            vk_code = int(event.vkCode)
            is_key_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            with self._state_lock:
                diagnostic_mode = self._capture_mode == "diagnostics"
            if diagnostic_mode:
                try:
                    self._diagnostic_events.put_nowait(
                        (
                            vk_code,
                            int(w_param),
                            int(event.scanCode),
                            int(event.flags),
                            int(event.time),
                        )
                    )
                except queue.Full:
                    with self._state_lock:
                        self._diagnostic_dropped_events += 1
                return user32.CallNextHookEx(
                    self._volume_hook, n_code, w_param, l_param
                )
            if not is_key_down:
                with self._state_lock:
                    was_captured = vk_code in self._captured_keys
                    was_pressed = vk_code in self._pressed_keys
                    self._captured_keys.discard(vk_code)
                    self._pressed_keys.discard(vk_code)
                    self._pressed_at.pop(vk_code, None)
                if was_captured or was_pressed:
                    return 1
            else:
                with self._state_lock:
                    if self._capture_mode:
                        if vk_code in self._pressed_keys:
                            elapsed = (
                                int(event.time)
                                - self._pressed_at.get(vk_code, int(event.time))
                            ) & 0xFFFFFFFF
                            if elapsed < 80:
                                return 1
                        self._pressed_keys.add(vk_code)
                        self._pressed_at[vk_code] = int(event.time)
                        self._captured_keys.add(vk_code)
                        self._capture_events.put(vk_code)
                        return 1
                    if vk_code == self.vk_increase:
                        increase = True
                    elif vk_code == self.vk_decrease:
                        increase = False
                    elif vk_code == VK_VOLUME_UP:
                        increase = True
                    elif vk_code == VK_VOLUME_DOWN:
                        increase = False
                    else:
                        increase = None
                    if increase is not None:
                        if vk_code in self._pressed_keys:
                            elapsed = (
                                int(event.time)
                                - self._pressed_at.get(vk_code, int(event.time))
                            ) & 0xFFFFFFFF
                            if elapsed < 80:
                                return 1
                        self._pressed_keys.add(vk_code)
                        self._pressed_at[vk_code] = int(event.time)
                        debug_mode = self.debug_mode
                    else:
                        debug_mode = False
                if increase is not None:
                    if debug_mode:
                        logger.debug("Captured %s key (VK 0x%02X)", "increase" if increase else "decrease", vk_code)
                    self._volume_events.put(increase)
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
                    new_volume = self.client.increase_volume(channel_name, step)
                else:
                    new_volume = self.client.decrease_volume(channel_name, step)
                if self.debug_mode:
                    logger.debug(
                        "Set Wave Link channel %r volume to %s%%",
                        channel_name,
                        new_volume,
                    )
        except WaveLinkError:
            logger.exception("Could not change Wave Link volume")
        except Exception:
            logger.exception("Unexpected error while changing Wave Link volume")

    @property
    def volume_hook_active(self) -> bool:
        return self._volume_hook_active

    @property
    def capture_mode(self) -> str | None:
        with self._state_lock:
            return self._capture_mode

    def begin_capture(self, mode: str) -> None:
        with self._state_lock:
            self._capture_mode = mode
        self._clear_capture_events()

    def end_capture(self) -> None:
        with self._state_lock:
            self._capture_mode = None
        self._clear_capture_events()

    def pop_capture_event(self) -> int | None:
        try:
            return self._capture_events.get_nowait()
        except queue.Empty:
            return None

    def pop_diagnostic_events(
        self, limit: int = 200
    ) -> tuple[list[tuple[int, int, int, int, int]], int]:
        events = []
        for _ in range(limit):
            try:
                events.append(self._diagnostic_events.get_nowait())
            except queue.Empty:
                break
        with self._state_lock:
            dropped_count = self._diagnostic_dropped_events
        return events, dropped_count

    def clear_diagnostic_events(self) -> None:
        while True:
            try:
                self._diagnostic_events.get_nowait()
            except queue.Empty:
                break
        with self._state_lock:
            self._diagnostic_dropped_events = 0

    def _clear_capture_events(self) -> None:
        while True:
            try:
                self._capture_events.get_nowait()
            except queue.Empty:
                return

    def _load_settings(self) -> None:
        if not self.context:
            return
        raw = self.context.load_settings(
            default={
                "channel_name": "Music",
                "step": 5,
                "hotkey_increase": "f13",
                "hotkey_decrease": "f14",
                "vk_increase": VK_F13,
                "vk_decrease": VK_F14,
                "debug_mode": False,
            }
        )
        channel_name = raw.get("channel_name", "Music")
        self.channel_name = str(channel_name).strip() or "Music"
        try:
            self.step = max(1, min(100, int(raw.get("step", 5))))
        except (TypeError, ValueError, OverflowError):
            self.step = 5
        self.vk_increase = self._valid_vk(raw.get("vk_increase"), VK_F13)
        self.vk_decrease = self._valid_vk(raw.get("vk_decrease"), VK_F14)
        if self.vk_increase == self.vk_decrease:
            self.vk_increase, self.vk_decrease = VK_F13, VK_F14
        self.hotkey_increase = str(raw.get("hotkey_increase", "f13"))
        self.hotkey_decrease = str(raw.get("hotkey_decrease", "f14"))
        self.debug_mode = bool(raw.get("debug_mode", raw.get("debug_all_keys", False)))

    @staticmethod
    def _valid_vk(value: object, fallback: int) -> int:
        try:
            vk_code = int(value)
        except (TypeError, ValueError, OverflowError):
            return fallback
        return vk_code if 1 <= vk_code <= 0xFF else fallback

    def _save_settings(self) -> None:
        if not self.context:
            return
        self.context.save_settings(
            {
                "channel_name": self.channel_name,
                "step": self.step,
                "hotkey_increase": self.hotkey_increase,
                "hotkey_decrease": self.hotkey_decrease,
                "vk_increase": self.vk_increase,
                "vk_decrease": self.vk_decrease,
                "debug_mode": self.debug_mode,
            }
        )

    def _configure_debug_logging(self) -> None:
        if self.debug_mode and self.context and self._debug_handler is None:
            log_path = self.context.writable_dir / "wavelink-debug.log"
            self._debug_handler = logging.FileHandler(log_path, encoding="utf-8")
            self._debug_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            self._debug_previous_level = logger.level
            logger.addHandler(self._debug_handler)
            logger.setLevel(logging.DEBUG)
        elif not self.debug_mode and self._debug_handler is not None:
            self._remove_debug_handler()

    def _remove_debug_handler(self) -> None:
        if self._debug_handler is None:
            return
        logger.removeHandler(self._debug_handler)
        self._debug_handler.close()
        self._debug_handler = None
        if self._debug_previous_level is not None:
            logger.setLevel(self._debug_previous_level)
            self._debug_previous_level = None

    def open_settings(self) -> None:
        if self.client is None:
            self.client = WaveLinkClient()
        channels_error = None
        try:
            channels = self.client.get_channels()
        except WaveLinkError as exc:
            logger.warning("Could not load Wave Link channel list: %s", exc)
            channels = []
            channels_error = f"Не удалось получить список каналов: {exc}"
        if self.channel_name not in channels:
            channels.insert(0, self.channel_name)

        dialog = WaveLinkSettingsDialog(
            self,
            channels,
            channels_error,
            parent=QApplication.activeModalWidget() or QApplication.activeWindow(),
        )
        if not dialog.exec():
            return

        settings = dialog.get_settings()
        channel_name = settings["channel_name"]
        with self._state_lock:
            self.channel_name = channel_name
            self.step = settings["step"]
            self.vk_increase = settings["vk_increase"]
            self.vk_decrease = settings["vk_decrease"]
            self.debug_mode = settings["debug_mode"]
        self._configure_debug_logging()
        self.hotkey_increase = _key_label(self.vk_increase).lower()
        self.hotkey_decrease = _key_label(self.vk_decrease).lower()
        self._save_settings()

    def stop(self) -> None:
        """Stops keyboard hooks and closes Wave Link connection."""
        self.end_capture()
        self._volume_hook_stop.set()
        if user32 is not None and self._volume_hook_thread_id:
            user32.PostThreadMessageW(self._volume_hook_thread_id, WM_QUIT, 0, 0)
        if self._volume_hook_thread:
            self._volume_hook_thread.join(timeout=2.0)
            self._volume_hook_thread = None
        self._volume_hook_active = False
        self._volume_events.put(None)
        if self._volume_worker:
            self._volume_worker.join(timeout=2.0)
            self._volume_worker = None

        if self.client:
            self.client.disconnect()
            self.client = None
        self._remove_debug_handler()

    def actions(self) -> list:
        return []
