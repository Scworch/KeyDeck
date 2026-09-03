from __future__ import annotations

from typing import Any
import winreg

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext

REGISTRY_PATH = (
    r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
)
VALUE_NAME = "_User_Global_VAL_SuperResolution"
VALID_MODES = ("off", "1", "2", "3", "4", "auto")
MODE_TO_VALUE = {"off": 0, "1": 1, "2": 2, "3": 3, "4": 4, "auto": 5}


class Plugin(PluginBase):
    plugin_id = "NvidiaRtxVideoSuperResolution"
    plugin_name = "NVIDIA RTX Video Super Resolution"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        defaults = {"mode_1": "off", "mode_2": "auto"}
        if self.context is not None:
            raw = self.context.load_settings(default=defaults)
            self.mode_1 = self._normalize_mode(raw.get("mode_1", defaults["mode_1"]), defaults["mode_1"])
            self.mode_2 = self._normalize_mode(raw.get("mode_2", defaults["mode_2"]), defaults["mode_2"])
            if self.mode_1 == self.mode_2:
                self.mode_2 = "auto" if self.mode_1 == "off" else "off"
            self._save_settings()
        else:
            self.mode_1 = defaults["mode_1"]
            self.mode_2 = defaults["mode_2"]

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id=f"{self.plugin_id}.toggle",
                title=self._button_title(),
                callback=self.toggle_mode,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
            )
        ]

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
            self.context.save_settings({"mode_1": self.mode_1, "mode_2": self.mode_2})

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
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
                value, reg_type = winreg.QueryValueEx(key, VALUE_NAME)
                if reg_type not in (winreg.REG_DWORD, winreg.REG_BINARY, winreg.REG_SZ):
                    return None
                return int(value)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            return None

    def _apply_mode(self, mode: str) -> None:
        mode_name = self._normalize_mode(mode, "off")
        requested_value = MODE_TO_VALUE.get(mode_name, 0)
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                REGISTRY_PATH,
                0,
                winreg.KEY_READ | winreg.KEY_WRITE,
            ) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, requested_value)
        except OSError as exc:  # pragma: no cover - runtime OS access path
            raise RuntimeError(
                "Unable to update NVIDIA RTX Video Super Resolution setting. "
                "Run KeyDeck with administrator privileges and confirm the registry key exists."
            ) from exc
