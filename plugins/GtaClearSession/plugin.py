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
from keydeck.ui.controls import SettingsSection, add_dialog_header, style_dialog_buttons
from keydeck.ui.theme import size_dialog

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.append(str(PLUGIN_DIR))

from gta_clear_session import ClearSessionSettings, run_async


class _Notifier(QObject):
    error = Signal(str)
    busy = Signal(str)


class Plugin(PluginBase):
    plugin_id = "GtaClearSession"
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
                icon_path=str(PLUGIN_DIR / "icon.png"),
                icon_mode="cover",
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
                aliases=["gta_clear_session.clear"],
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
        size_dialog(dialog, 780, 560, 600, 440)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)
        add_dialog_header(
            layout,
            "GTA Clear Session",
            "Choose the action label and process handling behavior.",
            dialog,
        )

        title_section = SettingsSection("Button", "This title appears on the assigned deck button.", dialog)
        title_form = QFormLayout()
        title_form.setContentsMargins(0, 0, 0, 0)
        title_section.content_layout.addLayout(title_form)

        title_edit = QLineEdit(self.settings.action_title, dialog)
        title_form.addRow("Button title", title_edit)

        process_section = SettingsSection(
            "Process handling",
            "Select the process names KeyDeck should handle and the suspend duration.",
            dialog,
        )
        process_form = QFormLayout()
        process_form.setContentsMargins(0, 0, 0, 0)
        process_section.content_layout.addLayout(process_form)
        process_names_edit = QLineEdit(", ".join(self.settings.process_names), dialog)
        process_names_edit.setPlaceholderText("GTA5_Enhanced.exe, GTA5.exe")
        process_form.addRow("Process names", process_names_edit)

        suspend_seconds_spin = QDoubleSpinBox(dialog)
        suspend_seconds_spin.setRange(1.0, 30.0)
        suspend_seconds_spin.setSingleStep(0.5)
        suspend_seconds_spin.setDecimals(1)
        suspend_seconds_spin.setValue(float(self.settings.suspend_seconds))
        process_form.addRow("Suspend duration", suspend_seconds_spin)

        layout.addWidget(title_section)
        layout.addWidget(process_section)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        style_dialog_buttons(buttons, QDialogButtonBox.StandardButton.Ok)
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
