from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.append(str(PLUGIN_DIR))

from gta_clear_session import ClearSessionSettings, run_async


class _Notifier(QObject):
    error = Signal(str)
    busy = Signal(str)


class Plugin(PluginBase):
    plugin_id = "gta_clear_session"
    plugin_name = "GTA Clear Session"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        defaults = ClearSessionSettings().to_dict()
        raw = self.context.load_settings(defaults) if self.context else defaults
        self.settings = ClearSessionSettings.from_dict(raw)
        if self.context:
            self.context.save_settings(self.settings.to_dict())

        self._notifier = _Notifier()
        self._notifier.error.connect(self._show_error)
        self._notifier.busy.connect(self._show_busy)

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id=f"{self.plugin_id}.clear",
                title=self.settings.action_title,
                callback=self.clear_session,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
            )
        ]

    def clear_session(self) -> None:
        run_async(
            settings=self.settings,
            on_error=self._notifier.error.emit,
            on_busy=self._notifier.busy.emit,
        )

    def open_settings(self) -> None:
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        dialog = QDialog(parent)
        dialog.setWindowTitle("GTA Clear Session settings")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)

        title_edit = QLineEdit(self.settings.action_title, dialog)
        form.addRow("Button title", title_edit)

        process_names_edit = QLineEdit(", ".join(self.settings.process_names), dialog)
        process_names_edit.setPlaceholderText("GTA5_Enhanced.exe, GTA5.exe")
        form.addRow("Process names", process_names_edit)

        suspend_seconds_spin = QDoubleSpinBox(dialog)
        suspend_seconds_spin.setRange(1.0, 30.0)
        suspend_seconds_spin.setSingleStep(0.5)
        suspend_seconds_spin.setDecimals(1)
        suspend_seconds_spin.setValue(float(self.settings.suspend_seconds))
        form.addRow("Suspend seconds", suspend_seconds_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if not dialog.exec():
            return

        process_names = [
            item.strip()
            for item in process_names_edit.text().split(",")
            if item.strip()
        ]
        if not process_names:
            QMessageBox.warning(None, "GTA Clear Session", "At least one process name is required.")
            return

        self.settings = ClearSessionSettings.from_dict(
            {
                "action_title": title_edit.text().strip() or ClearSessionSettings().action_title,
                "process_names": process_names,
                "suspend_seconds": float(suspend_seconds_spin.value()),
            }
        )
        if self.context:
            self.context.save_settings(self.settings.to_dict())

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(None, "GTA Clear Session", message)

    def _show_busy(self, message: str) -> None:
        QMessageBox.information(None, "GTA Clear Session", message)
