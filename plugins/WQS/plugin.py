from __future__ import annotations

import atexit
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from keydeck.plugin_api import Action, PluginBase, PluginContext

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from actions import ActionEngine
from models import SettingsStore
from network import NetworkManager
from ui import Launcher, SettingsDialog
from window_manager import WindowManager


class Plugin(PluginBase):
    plugin_id = "WQS"
    plugin_name = "WQS - Windows Quick Start"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context)
        if context is None:
            raise ValueError("WQS requires PluginContext")
        self.store = SettingsStore(context.settings_file)
        self.settings = self.store.load()
        self._migrate_icon_paths()
        self.presets = self.settings["presets"]
        self.window: Launcher | None = None
        self.window_manager = WindowManager()
        self._taskbar_hidden = False
        self._log_lock = threading.Lock()
        self.action_engine = ActionEngine(self.log)
        self.network = NetworkManager(
            context.plugin_dir,
            self.log,
            data_plugins_dir=context.writable_dir.parent,
        )
        atexit.register(self.restore_desktop)

    def actions(self) -> list[Action]:
        icon = self.context.plugin_dir / "icons" / "Logo_Windows_11.webp"
        return [Action(
            action_id="WQS.launcher", title="WQS Quick Start", callback=self.show_launcher,
            plugin_id=self.plugin_id, settings_callback=self.open_settings,
            icon_path=str(icon) if icon.exists() else None
        )]

    def start(self) -> None:
        if self.settings["general"].get("autorun", False):
            QTimer.singleShot(0, self.show_launcher)

    def stop(self) -> None:
        self.restore_desktop()
        if self.window:
            self.window.close()

    def show_launcher(self) -> None:
        if self.window and self.window.isVisible():
            self.window.raise_()
            return
        self.window = Launcher(self, QApplication.activeWindow())
        self.hide_taskbar()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _migrate_icon_paths(self) -> None:
        icon_map = {
            "windows.svg": "icons/Logo_Windows_11.webp",
            "steam.svg": "icons/Steam_icon_logo.svg",
            "epic.svg": "icons/Epic_Games_logo.svg",
            "vscode.svg": "icons/Visual_Studio_Code_1.35_icon.svg",
        }
        changed = False
        for preset in self.settings.get("presets", []):
            icon = str(preset.get("icon", ""))
            if icon in icon_map:
                preset["icon"] = icon_map[icon]
                changed = True
        if changed:
            self.store.data = self.settings
            self.store.save()

    def launch_preset(self, preset: dict[str, Any]) -> None:
        mode = str(preset.get("network", {}).get("mode", self.settings["network"].get("default_mode", "off")))
        server = str(preset.get("network", {}).get("server", ""))
        if self.window and self.window.mode.currentData() != "off":
            mode = str(self.window.mode.currentData())
            server = self.window.server.currentText()
        self.start_network(mode, server)
        for app in preset.get("apps", []):
            ok, message = self.window_manager.launch(app)
            self.log(ok, message)
        self.action_engine.run(preset.get("actions", []))
        apps = list(preset.get("apps", []))
        threading.Thread(target=self.window_manager.wait_and_place, args=(apps,), daemon=True).start()
        if self.settings["general"].get("close_after_launch", True) and self.window:
            self.window.close()

    def start_network(self, mode: str, server: str = "") -> bool:
        return self.network.start(mode, self.settings["network"], server)

    def log(self, success: bool, message: str) -> None:
        with self._log_lock:
            entry = {"success": success, "message": message}
            self.settings.setdefault("run_log", []).append(entry)
            self.settings["run_log"] = self.settings["run_log"][-200:]
            self.store.save()

    def replace_settings(self, data: dict[str, Any]) -> None:
        self.settings = self.store._merge(self.settings, data)
        self.store.data = self.settings
        self.store.save()
        self.presets = self.settings.get("presets", [])

    def open_settings(self) -> None:
        dialog = SettingsDialog(self, QApplication.activeWindow())
        dialog.exec()

    def restore_desktop(self) -> None:
        if not self._taskbar_hidden:
            return
        self._taskbar_hidden = False
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None), 5)
        except (AttributeError, OSError):
            pass

    def hide_taskbar(self) -> None:
        if not self.settings["general"].get("hide_taskbar", True) or self._taskbar_hidden:
            return
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None), 0
            )
            self._taskbar_hidden = True
        except (AttributeError, OSError):
            self.log(False, "Не удалось скрыть панель задач")
