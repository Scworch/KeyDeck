from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from vsr import read_vsr, set_vsr

REGISTRY_PATH = (
    r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
)
VALUE_NAME = "_User_Global_VAL_SuperResolution"
VALID_MODES = ("off", "1", "2", "3", "4", "auto")
MODE_TO_VALUE = {"off": 0, "1": 1, "2": 2, "3": 3, "4": 4, "auto": 5}
MODE_ICON_FILES = {
    "off": "OFF.png",
    "1": "1.png",
    "2": "2.png",
    "3": "3.png",
    "4": "4.png",
    "auto": "AUTO.png",
}
ICON_DIR = Path(__file__).resolve().parent / "icons"


class Plugin(PluginBase):
    plugin_id = "NvidiaRtxVideoSuperResolution"
    plugin_name = "NVIDIA RTX Video Super Resolution"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        defaults = {"mode_1": "off", "mode_2": "auto", "disable_in_games": False}
        if self.context is not None:
            raw = self.context.load_settings(default=defaults)
            self.mode_1 = self._normalize_mode(raw.get("mode_1", defaults["mode_1"]), defaults["mode_1"])
            self.mode_2 = self._normalize_mode(raw.get("mode_2", defaults["mode_2"]), defaults["mode_2"])
            self.disable_in_games = bool(raw.get("disable_in_games", defaults["disable_in_games"]))
            if self.mode_1 == self.mode_2:
                self.mode_2 = "auto" if self.mode_1 == "off" else "off"
            self._save_settings()
        else:
            self.mode_1 = defaults["mode_1"]
            self.mode_2 = defaults["mode_2"]
            self.disable_in_games = defaults["disable_in_games"]
        self._game_timer: QTimer | None = None
        self._game_forced_off = False

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id=f"{self.plugin_id}.toggle",
                title=self._button_title(),
                callback=self.toggle_mode,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
                action_icon_callback=self._get_action_icon,
                icon_path=str(ICON_DIR / "OFF.png"),
                icon_mode="contain",
                icon_zoom=0.9,
            )
        ]

    def _get_action_icon(self, slot: int, current_settings: dict) -> str | None:
        mode = self._read_mode_name()
        filename = MODE_ICON_FILES.get(mode or "")
        if filename is None:
            return None
        icon_path = ICON_DIR / filename
        return str(icon_path) if icon_path.exists() else None

    def open_settings(self) -> None:
        if self.context is None:
            return

        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        dialog = QDialog(parent)
        dialog.setWindowTitle("NVIDIA RTX Video Super Resolution settings")
        dialog.setModal(True)
        dialog.setMinimumWidth(420)
        dialog.setMinimumHeight(180)

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        mode_1_box = QComboBox(dialog)
        mode_1_box.setMinimumWidth(150)
        mode_1_box.addItems(list(VALID_MODES))
        mode_1_box.setCurrentText(self.mode_1)
        form.addRow("Mode 1", mode_1_box)

        mode_2_box = QComboBox(dialog)
        mode_2_box.setMinimumWidth(150)
        mode_2_box.addItems(list(VALID_MODES))
        mode_2_box.setCurrentText(self.mode_2)
        form.addRow("Mode 2", mode_2_box)

        disable_games = QCheckBox("Automatically disable VSR while a game is running", dialog)
        disable_games.setChecked(self.disable_in_games)
        form.addRow(disable_games)

        main_layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        main_layout.addWidget(buttons)

        if not dialog.exec():
            return

        mode_1 = self._normalize_mode(mode_1_box.currentText(), "off")
        mode_2 = self._normalize_mode(mode_2_box.currentText(), "auto")
        if mode_1 == mode_2:
            if mode_1 == "off":
                mode_2 = "auto"
            else:
                mode_2 = "off"
        self.mode_1 = mode_1
        self.mode_2 = mode_2
        self.disable_in_games = disable_games.isChecked()
        self._save_settings()

    def toggle_mode(self) -> None:
        current = self._read_mode_name()
        if current == self.mode_1:
            target = self.mode_2
        elif current == self.mode_2:
            target = self.mode_1
        else:
            target = self.mode_1
        self._apply_mode(target)

    def _button_title(self) -> str:
        current = self._read_mode_name()
        if current is None:
            current = "unknown"
        return f"RTX Video: {current}"

    def _save_settings(self) -> None:
        if self.context is not None:
            self.context.save_settings(
                {
                    "mode_1": self.mode_1,
                    "mode_2": self.mode_2,
                    "disable_in_games": self.disable_in_games,
                }
            )

    def start(self) -> None:
        self._game_timer = QTimer()
        self._game_timer.timeout.connect(self._check_game_state)
        self._game_timer.start(3000)

    def stop(self) -> None:
        if self._game_timer is not None:
            self._game_timer.stop()
            self._game_timer.deleteLater()
            self._game_timer = None

    def _check_game_state(self) -> None:
        if not self.disable_in_games:
            self._game_forced_off = False
            return
        running = self._game_process_running()
        if running and not self._game_forced_off:
            self._apply_mode("off")
            self._game_forced_off = True
        elif not running:
            self._game_forced_off = False

    def _game_process_running(self) -> bool:
        try:
            import psutil
        except ImportError:
            return self._game_process_running_from_tasklist()

        markers = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\games\\")
        for process in psutil.process_iter(["exe"]):
            try:
                executable = (process.info.get("exe") or "").casefold()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if any(marker in executable for marker in markers):
                return True
        return False

    def _game_process_running_from_tasklist(self) -> bool:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process -ErrorAction SilentlyContinue | ForEach-Object { "
                "try { $_.Path } catch {} }",
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        markers = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\games\\")
        for line in result.stdout.splitlines():
            if any(marker in line.casefold() for marker in markers):
                return True
        return False

    def _normalize_mode(self, value: Any, fallback: str) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in VALID_MODES:
                return normalized
        return fallback

    def _read_mode_name(self) -> str | None:
        value = self._read_registry_value()
        if value is None:
            return None
        mode_map = {
            0: "off",
            1: "1",
            2: "2",
            3: "3",
            4: "4",
            5: "auto",
        }
        return mode_map.get(value)

    def _read_registry_value(self) -> int | None:
        try:
            state = read_vsr()
            value = state.get("value")
            if not isinstance(value, dict) or value.get("type") != 4:
                return None
            return int(value.get("value"))
        except (FileNotFoundError, OSError, TypeError, ValueError, RuntimeError):
            return None

    def _apply_mode(self, mode: str) -> None:
        mode_name = self._normalize_mode(mode, "off")
        set_vsr(mode_name)
