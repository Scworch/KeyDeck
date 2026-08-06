#KeyDeck/plugins/ResolutionSwitcher/plugin.py
from __future__ import annotations

from dataclasses import asdict, dataclass
import sys
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.append(str(PLUGIN_DIR))

import resolution_switch


@dataclass
class SwitcherSettings:
    button_original_title: str = "Resolution: Original"
    button_target_title: str = "Resolution: 1920x1440"
    target_width: int = 1920
    target_height: int = 1440
    auto_switch_executables: list[str] | None = None
    original_width: int = 0
    original_height: int = 0
    original_frequency: int = 0
    original_bits_per_pixel: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "SwitcherSettings":
        defaults = cls()
        return cls(
            button_original_title=str(
                data.get("button_original_title", defaults.button_original_title)
            ),
            button_target_title=str(data.get("button_target_title", defaults.button_target_title)),
            target_width=int(data.get("target_width", defaults.target_width)),
            target_height=int(data.get("target_height", defaults.target_height)),
            auto_switch_executables=[
                str(item).strip()
                for item in data.get("auto_switch_executables", ["cs2.exe"])
                if str(item).strip()
            ],
            original_width=int(data.get("original_width", defaults.original_width)),
            original_height=int(data.get("original_height", defaults.original_height)),
            original_frequency=int(data.get("original_frequency", defaults.original_frequency)),
            original_bits_per_pixel=int(
                data.get("original_bits_per_pixel", defaults.original_bits_per_pixel)
            ),
        ).clamp()

    def clamp(self) -> "SwitcherSettings":
        self.target_width = max(640, min(self.target_width, 16384))
        self.target_height = max(480, min(self.target_height, 16384))
        self.auto_switch_executables = [
            item.strip()
            for item in (self.auto_switch_executables or ["cs2.exe"])
            if item and item.strip()
        ] or ["cs2.exe"]
        return self

    def to_dict(self) -> dict:
        return asdict(self)


class Plugin(PluginBase):
    plugin_id = "ResolutionSwitcher"
    plugin_name = "Resolution Switcher"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        raw = self.context.load_settings({}) if self.context else {}
        self.settings = SwitcherSettings.from_dict(raw)
        self._auto_switched_to_target = False
        self._auto_switch_blocked_for_current_session = False
        self._ensure_original_mode_snapshot()
        self._save_settings()
        self._auto_timer = QTimer()
        self._auto_timer.setInterval(2000)
        self._auto_timer.timeout.connect(self._auto_apply_for_processes)
        self._auto_timer.start()

    def actions(self) -> list[Action]:
        toggle_title = self._toggle_title()
        return [
            Action(
                action_id=f"{self.plugin_id}.toggle",
                title=toggle_title,
                callback=self.toggle_resolution,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
                aliases=[
                    f"{self.plugin_id}.to_original",
                    f"{self.plugin_id}.to_target",
                ],
            )
        ]

    def toggle_resolution(self) -> None:
        watched_running = self._is_any_watched_process_running()
        if self._is_current_mode_target():
            self.switch_to_original()
            self._auto_switched_to_target = False
            self._auto_switch_blocked_for_current_session = watched_running
        else:
            self.switch_to_target()
            self._auto_switched_to_target = False
            self._auto_switch_blocked_for_current_session = False

    def switch_to_original(self) -> None:
        self._ensure_original_mode_snapshot()
        mode = resolution_switch.DisplayMode(
            width=self.settings.original_width,
            height=self.settings.original_height,
            frequency=self.settings.original_frequency,
            bits_per_pixel=self.settings.original_bits_per_pixel,
        )
        if mode.frequency <= 0:
            raise RuntimeError("Original mode is not initialized")
        resolution_switch.apply_mode(mode)

    def switch_to_target(self) -> None:
        target = resolution_switch.switch_resolution_keep_frequency(
            self.settings.target_width,
            self.settings.target_height,
        )
        # Keep label informative after successful switch.
        self.settings.button_target_title = (
            self.settings.button_target_title
            or f"Resolution: {target.width}x{target.height}"
        )
        self._save_settings()

    def open_settings(self) -> None:
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        dialog = QDialog(parent)
        dialog.setWindowTitle("ResolutionSwitcher settings")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)

        title_original = QLineEdit(self.settings.button_original_title, dialog)
        form.addRow("Title when switching to original", title_original)

        title_target = QLineEdit(self.settings.button_target_title, dialog)
        form.addRow("Title when switching to target", title_target)

        width_spin = QSpinBox(dialog)
        width_spin.setRange(640, 16384)
        width_spin.setValue(self.settings.target_width)
        form.addRow("Target width", width_spin)

        height_spin = QSpinBox(dialog)
        height_spin.setRange(480, 16384)
        height_spin.setValue(self.settings.target_height)
        form.addRow("Target height", height_spin)

        auto_switch_edit = QLineEdit(", ".join(self.settings.auto_switch_executables), dialog)
        auto_switch_edit.setPlaceholderText("cs2.exe, game.exe")
        form.addRow("Auto switch for .exe", auto_switch_edit)

        current = resolution_switch.current_mode()
        current_info = QLineEdit(
            f"{current.width}x{current.height} @ {current.frequency}Hz",
            dialog,
        )
        current_info.setReadOnly(True)
        form.addRow("Current mode", current_info)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec():
            self.settings.button_original_title = title_original.text().strip() or "Original"
            self.settings.button_target_title = title_target.text().strip() or "1920x1440"
            self.settings.target_width = width_spin.value()
            self.settings.target_height = height_spin.value()
            self.settings.auto_switch_executables = [
                item.strip()
                for item in auto_switch_edit.text().split(",")
                if item.strip()
            ] or ["cs2.exe"]
            self.settings.clamp()
            self._save_settings()

    def _toggle_title(self) -> str:
        if self._is_current_mode_target():
            return self.settings.button_original_title
        return self.settings.button_target_title

    def _is_current_mode_target(self) -> bool:
        current = resolution_switch.current_mode()
        return (
            current.width == self.settings.target_width
            and current.height == self.settings.target_height
        )

    def _ensure_original_mode_snapshot(self) -> None:
        if self.settings.original_width > 0 and self.settings.original_height > 0:
            return
        mode = resolution_switch.current_mode()
        self.settings.original_width = mode.width
        self.settings.original_height = mode.height
        self.settings.original_frequency = mode.frequency
        self.settings.original_bits_per_pixel = mode.bits_per_pixel

    def _save_settings(self) -> None:
        if self.context:
            self.context.save_settings(self.settings.to_dict())

    def _auto_apply_for_processes(self) -> None:
        try:
            watched_running = self._is_any_watched_process_running()
            if not watched_running:
                if self._auto_switched_to_target and self._is_current_mode_target():
                    self.switch_to_original()
                self._auto_switched_to_target = False
                self._auto_switch_blocked_for_current_session = False
                return

            if self._auto_switch_blocked_for_current_session:
                return

            if watched_running and not self._is_current_mode_target():
                self.switch_to_target()
                self._auto_switched_to_target = True
                return
        except Exception:
            return

    def _is_any_watched_process_running(self) -> bool:
        wanted = {name.lower() for name in self.settings.auto_switch_executables or []}
        if not wanted:
            return False
        for proc in psutil.process_iter(["name"]):
            try:
                name = str(proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name in wanted:
                return True
        return False
