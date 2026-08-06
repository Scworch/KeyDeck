from __future__ import annotations

import os
import glob
import ctypes
from pathlib import Path
from typing import Optional

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QCheckBox,
    QLabel,
    QMessageBox,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext

def get_zapret_dir() -> Optional[Path]:
    # Find matching directory in C:\
    matches = glob.glob(r"C:\zapret-discord-youtube-*")
    if not matches:
        return None
    # Sort by modification time or just pick the first one
    matches.sort(key=os.path.getmtime, reverse=True)
    return Path(matches[0])

def get_bat_files(zapret_dir: Path) -> list[str]:
    if not zapret_dir or not zapret_dir.exists() or not zapret_dir.is_dir():
        return []
    bat_files = []
    for p in zapret_dir.iterdir():
        if p.is_file() and p.suffix.lower() == '.bat':
            bat_files.append(p.name)
    bat_files.sort()
    return bat_files

def is_zapret_running() -> bool:
    for p in psutil.process_iter(['name']):
        try:
            if p.info['name'] and p.info['name'].lower() == 'winws.exe':
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def stop_zapret() -> None:
    try_elevated_kill = False
    for p in psutil.process_iter(['name']):
        try:
            if p.info['name'] and p.info['name'].lower() == 'winws.exe':
                p.kill()
        except psutil.AccessDenied:
            try_elevated_kill = True
        except psutil.NoSuchProcess:
            pass
            
    if try_elevated_kill:
        # Fallback: use taskkill elevated to kill winws.exe
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "taskkill",
            "/F /IM winws.exe",
            None,
            0 # SW_HIDE
        )

def start_zapret(bat_path: Path) -> None:
    if bat_path.exists():
        # Using ShellExecute with 'runas' to elevate privileges
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(bat_path),
            "",
            str(bat_path.parent),
            1 # SW_SHOWNORMAL
        )

class SettingsDialog(QDialog):
    def __init__(
        self,
        current_bat: str,
        autorun: bool,
        zapret_dir: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ZapretToggler Settings")
        self.setModal(True)
        self.setMinimumWidth(400)

        main_layout = QVBoxLayout(self)

        form = QFormLayout()
        main_layout.addLayout(form)

        # Directory status
        dir_label = QLabel()
        if zapret_dir:
            dir_label.setText(f"Found: {zapret_dir}")
            dir_label.setStyleSheet("color: #4CAF50;") # Green
        else:
            dir_label.setText("Not found! Please ensure C:\\zapret-discord-youtube-* exists.")
            dir_label.setStyleSheet("color: #F44336;") # Red
        form.addRow("Zapret Directory:", dir_label)

        # Bat file selection
        self.bat_combo = QComboBox(self)
        if zapret_dir:
            bat_files = get_bat_files(zapret_dir)
            self.bat_combo.addItems(bat_files)
            if current_bat in bat_files:
                self.bat_combo.setCurrentText(current_bat)
        form.addRow("Select script:", self.bat_combo)

        # Autorun checkbox
        self.autorun_check = QCheckBox("Run script automatically when KeyDeck starts", self)
        self.autorun_check.setChecked(autorun)
        form.addRow("Autorun:", self.autorun_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def get_settings(self) -> tuple[str, bool]:
        return self.bat_combo.currentText(), self.autorun_check.isChecked()


class Plugin(PluginBase):
    plugin_id = "ZapretToggler"
    plugin_name = "Zapret Toggler"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        
        self.selected_bat = ""
        self.autorun = False
        self._load_settings()

        # Execute autorun
        if self.autorun and self.selected_bat:
            zapret_dir = get_zapret_dir()
            if zapret_dir:
                bat_path = zapret_dir / self.selected_bat
                if not is_zapret_running():
                    start_zapret(bat_path)

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id=f"{self.plugin_id}.toggle",
                title="Toggle Zapret",
                callback=self._toggle_zapret,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
                icon_path=self._get_icon_path(),
            )
        ]
        
    def _get_icon_path(self) -> str | None:
        # Check if there is an icon in the plugin directory
        if self.context:
            icon_path = self.context.plugin_dir / "icon.png"
            if icon_path.exists():
                return str(icon_path)
        return None

    def open_settings(self) -> None:
        zapret_dir = get_zapret_dir()
        
        dialog = SettingsDialog(
            current_bat=self.selected_bat,
            autorun=self.autorun,
            zapret_dir=zapret_dir,
            parent=QApplication.activeModalWidget() or QApplication.activeWindow(),
        )
        if not dialog.exec():
            return

        selected_bat, autorun = dialog.get_settings()
        self.selected_bat = selected_bat
        self.autorun = autorun
        self._save_settings()

    def _toggle_zapret(self) -> None:
        if is_zapret_running():
            stop_zapret()
        else:
            zapret_dir = get_zapret_dir()
            if not zapret_dir:
                QMessageBox.warning(None, "ZapretToggler", "Zapret directory not found on C: drive.")
                return
                
            if not self.selected_bat:
                QMessageBox.warning(None, "ZapretToggler", "No .bat script selected. Please open settings.")
                return
                
            bat_path = zapret_dir / self.selected_bat
            if not bat_path.exists():
                QMessageBox.warning(None, "ZapretToggler", f"Script not found: {bat_path}")
                return
                
            start_zapret(bat_path)

    def _load_settings(self) -> None:
        if not self.context:
            return
        raw = self.context.load_settings(default={"selected_bat": "", "autorun": False})
        self.selected_bat = raw.get("selected_bat", "")
        self.autorun = bool(raw.get("autorun", False))

    def _save_settings(self) -> None:
        if not self.context:
            return
        self.context.save_settings(
            {
                "selected_bat": self.selected_bat,
                "autorun": self.autorun,
            }
        )
