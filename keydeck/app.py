from __future__ import annotations

import http.client
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from keydeck import __version__
from keydeck.config import (
    ICONS_DIR,
    PLUGINS_DIR,
    PLUGIN_DATA_DIR,
    AppSettings,
    load_settings,
    save_settings,
)
from keydeck.plugin_api import Action
from keydeck.plugin_manager import PluginManager
from keydeck.updates import (
    Release,
    UpdateCancelled,
    check_latest_release,
    download_release,
    launch_update_helper,
)
from keydeck.ui.deck_window import DeckWindow
from keydeck.ui.settings_dialog import SettingsDialog
from keydeck.ui.theme import apply_dark_theme


class UpdateWorker(QThread):
    checked = Signal(object)
    downloaded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, release: Release | None = None) -> None:
        super().__init__()
        self.release = release
        self._cancel_event = threading.Event()

    def run(self) -> None:
        try:
            if self.release is None:
                self.checked.emit(check_latest_release(self._cancel_event))
            else:
                self.downloaded.emit(
                    *download_release(self.release, self._cancel_event)
                )
        except UpdateCancelled:
            return
        except (http.client.HTTPException, OSError, ValueError) as exc:
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self._cancel_event.set()


class KeyDeckApplication(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName("KeyDeck")
        self.qt_app.setQuitOnLastWindowClosed(False)
        apply_dark_theme(self.qt_app)

        self.settings: AppSettings = load_settings()
        legacy_plugins_dir = (
            Path(sys.executable).resolve().parent / "plugins"
            if getattr(sys, "frozen", False)
            else None
        )
        self.plugin_manager = PluginManager(
            PLUGINS_DIR,
            data_dir=PLUGIN_DATA_DIR,
            legacy_data_dir=legacy_plugins_dir,
        )
        self.plugin_manager.load_plugins()
        self.plugin_manager.start_plugins()
        self.qt_app.aboutToQuit.connect(self.plugin_manager.stop_plugins)
        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=True)


        self.deck_window = DeckWindow(
            settings=self.settings,
            actions=actions,
        )
        self.deck_window.settings_requested.connect(self._open_settings)
        self.deck_window.action_requested.connect(self._run_action)
        self.deck_window.page_changed.connect(self._on_page_changed)
        self.deck_window.blur_hide_requested.connect(self._hide_on_blur)

        from keydeck.hotkey_manager import HotkeyManager

        self._is_settings_open = False
        self._update_worker: UpdateWorker | None = None
        self._manual_update_check = False
        self.tray_icon = self._create_tray()
        self.tray_icon.show()
        self.qt_app.aboutToQuit.connect(self._stop_update_worker)
        QTimer.singleShot(2500, self.check_for_updates)

        self.hotkey_manager = HotkeyManager(self._execute_slot, self.toggle_window)
        self.hotkey_manager.apply_hotkeys(
            self.settings.slot_hotkeys,
            self.settings.right_alt_toggle,
        )
        self.qt_app.aboutToQuit.connect(self.hotkey_manager.stop)

    def _execute_slot(self, slot_key: str) -> None:
        slot_ref = self.settings.resolve_hotkey_key(slot_key)
        if slot_ref is None:
            return
        page_index, slot = slot_ref
        page = self.settings.pages[page_index]
        action_id = page.slot_actions[slot]
        if not action_id:
            return
        
        # Find the action by ID
        action = None
        for a in self.deck_window.actions:
            if a.action_id == action_id:
                action = a
                break
                
        if action:
            self._run_action(action, slot, page_index)

    def _create_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self._load_tray_icon(), self.qt_app)
        tray.setToolTip("KeyDeck")
        tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        toggle_action = QAction("Show / Hide Deck", menu)
        toggle_action.triggered.connect(self.toggle_window)

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._open_settings)

        updates_action = QAction("Check for Updates", menu)
        updates_action.triggered.connect(lambda: self.check_for_updates(manual=True))

        reload_action = QAction("Reload Plugins", menu)
        reload_action.triggered.connect(self.reload_plugins)

        restart_action = QAction("Restart", menu)
        restart_action.triggered.connect(self.restart_application)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.qt_app.quit)

        menu.addAction(toggle_action)
        menu.addAction(settings_action)
        menu.addAction(updates_action)
        menu.addAction(reload_action)
        menu.addAction(restart_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)

        return tray

    def _load_tray_icon(self) -> QIcon:
        custom_icon = ICONS_DIR / "tray.png"
        if custom_icon.exists():
            return QIcon(str(custom_icon))
        return self._build_default_icon()

    def _build_default_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        cell = 10
        gap = 4
        grid_size = cell * 3 + gap * 2
        start_x = (64 - grid_size) // 2
        start_y = (64 - grid_size) // 2
        for row in range(3):
            for col in range(3):
                x = start_x + col * (cell + gap)
                y = start_y + row * (cell + gap)
                painter.drawRect(x, y, cell, cell)

        painter.end()
        return QIcon(pixmap)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window()

    def toggle_window(self) -> None:
        if self.deck_window.isVisible():
            self.deck_window.hide()
            return

        self.deck_window.show()
        self.deck_window.raise_()
        self.deck_window.activateWindow()

    def _on_page_changed(self, page_index: int) -> None:
        self.settings.active_page = page_index
        save_settings(self.settings)

    def _hide_on_blur(self) -> None:
        if self._is_settings_open:
            return
        if self.deck_window.isVisible():
            self.deck_window.hide()



    def _open_settings(self) -> None:
        self._is_settings_open = True
        try:
            dialog = SettingsDialog(
                self.settings,
                self.deck_window.actions,
                plugins=self.plugin_manager.get_plugins(),
                plugin_errors=self.plugin_manager.errors,
                reload_plugins_callback=self._load_plugins_for_settings,
                parent=self.deck_window,
            )

            if dialog.exec():
                new_settings = dialog.to_settings().clamp()
                
                # Check for autostart changes
                if self.settings.auto_start != new_settings.auto_start:
                    self._update_autostart_task(new_settings.auto_start)
                
                self.settings = new_settings
                save_settings(self.settings)
                self.deck_window.update_actions(dialog.actions)
                self.deck_window.apply_settings(self.settings)
                self.hotkey_manager.apply_hotkeys(
                    self.settings.slot_hotkeys,
                    self.settings.right_alt_toggle,
                )
        finally:
            self._is_settings_open = False

    def _update_autostart_task(self, enable: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            if enable:
                import tempfile
                from xml.sax.saxutils import escape

                exe_path = sys.executable
                if getattr(sys, "frozen", False):
                    arguments = ""
                    working_directory = str(Path(sys.executable).resolve().parent)
                else:
                    arguments = "-m keydeck"
                    working_directory = str(Path(__file__).resolve().parent.parent)
                xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>KeyDeck</Author>
    <URI>\\KeyDeck_AutoStart</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe_path)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(working_directory)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
                with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", encoding="utf-16", delete=False) as f:
                    f.write(xml_content)
                    temp_xml = f.name
                
                subprocess.run(
                    ["schtasks", "/Create", "/TN", "KeyDeck_AutoStart", "/XML", temp_xml, "/F"],
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                Path(temp_xml).unlink(missing_ok=True)
            else:
                subprocess.run(
                    ["schtasks", "/Delete", "/TN", "KeyDeck_AutoStart", "/F"],
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
        except Exception as e:
            print(f"Failed to update Task Scheduler: {e}")


    def _run_action(self, action: Action | None, slot: int = -1, page_index: int = 0) -> None:
        if action is None:
            return

        try:
            # Check if callback expects a slot argument
            import inspect
            sig = inspect.signature(action.callback)
            if len(sig.parameters) > 0:
                if 0 <= page_index < len(self.settings.pages):
                    settings = self.settings.pages[page_index].slot_settings.get(str(slot), {})
                else:
                    settings = {}
                action.callback(settings)
            else:
                action.callback()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.deck_window, "Action Failed", str(exc))
            return

        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=True)
        self.deck_window.update_actions(actions)

    def reload_plugins(self) -> None:
        self.plugin_manager.load_plugins()
        self.plugin_manager.start_plugins()
        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=True)
        self.deck_window.update_actions(actions)
        self.deck_window.apply_settings(self.settings)


        if self.plugin_manager.errors:
            details = "\n".join(self.plugin_manager.errors)
            QMessageBox.warning(
                self.deck_window,
                "Plugin Loader",
                f"Some plugins failed to load:\n{details}",
            )

    def _load_plugins_for_settings(self) -> list[Action]:
        self.plugin_manager.load_plugins()
        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=False)
        return actions

    def _normalize_settings_actions(self, actions: list[Action], persist: bool) -> None:
        valid_action_ids = {action.action_id for action in actions}
        aliases: dict[str, str] = {}
        for action in actions:
            for alias in action.aliases:
                aliases[str(alias)] = action.action_id
        if self.settings.normalize_action_ids(valid_action_ids, aliases) and persist:
            save_settings(self.settings)

    def restart_application(self) -> None:
        if getattr(sys, "frozen", False):
            command = [sys.executable]
            working_directory = str(Path(sys.executable).resolve().parent)
        else:
            command = [sys.executable, "-m", "keydeck"]
            working_directory = str(Path(__file__).resolve().parent.parent)
        subprocess.Popen(command, cwd=working_directory, close_fds=True)
        self.qt_app.quit()

    def check_for_updates(self, manual: bool = False) -> None:
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        self._manual_update_check = manual
        worker = UpdateWorker()
        worker.checked.connect(self._on_update_checked)
        worker.failed.connect(self._on_update_check_failed)
        worker.finished.connect(self._on_update_worker_finished)
        self._update_worker = worker
        worker.start()

    def _on_update_checked(self, release: Release | None) -> None:
        if release is None:
            if self._manual_update_check:
                QMessageBox.information(
                    self.deck_window,
                    "KeyDeck updates",
                    f"KeyDeck {__version__} is up to date.",
                )
            return

        message = QMessageBox(self.deck_window)
        message.setIcon(QMessageBox.Information)
        message.setWindowTitle("KeyDeck update available")
        message.setText(f"KeyDeck {release.version} is available.")
        if getattr(sys, "frozen", False):
            message.setInformativeText(
                "Install the update now? Your KeyDeck and plugin settings will be kept."
            )
        else:
            message.setInformativeText(
                "Open the release page to download the Windows executable. "
                "Your source installation will not be modified."
            )
        update_button = message.addButton("Update", QMessageBox.AcceptRole)
        message.addButton("Later", QMessageBox.RejectRole)
        message.exec()
        if message.clickedButton() != update_button:
            return

        if not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(release.page_url))
            return

        self.tray_icon.showMessage(
            "KeyDeck update",
            "Downloading and verifying the update...",
            QSystemTrayIcon.Information,
        )
        worker = UpdateWorker(release)
        worker.downloaded.connect(self._on_update_downloaded)
        worker.failed.connect(self._on_update_download_failed)
        worker.finished.connect(self._on_update_worker_finished)
        self._update_worker = worker
        worker.start()

    def _on_update_check_failed(self, error: str) -> None:
        message = f"Could not check for updates: {error}"
        if self._manual_update_check:
            QMessageBox.warning(self.deck_window, "KeyDeck updates", message)
        else:
            self.tray_icon.showMessage(
                "KeyDeck updates",
                message,
                QSystemTrayIcon.Warning,
            )

    def _on_update_download_failed(self, error: str) -> None:
        QMessageBox.critical(
            self.deck_window,
            "KeyDeck update",
            f"The update could not be downloaded or verified. KeyDeck was not changed.\n\n{error}",
        )

    def _on_update_downloaded(self, executable: Path, download_dir: Path) -> None:
        try:
            launch_update_helper(
                executable,
                download_dir,
                Path(sys.executable).resolve(),
                os.getpid(),
            )
        except OSError as exc:
            shutil.rmtree(download_dir, ignore_errors=True)
            QMessageBox.critical(
                self.deck_window,
                "KeyDeck update",
                f"The update could not be started. KeyDeck was not changed.\n\n{exc}",
            )
            return
        self.qt_app.quit()

    def _on_update_worker_finished(self) -> None:
        worker = self.sender()
        if worker is self._update_worker:
            self._update_worker = None

    def _stop_update_worker(self) -> None:
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.cancel()
            self._update_worker.wait()

    def run(self) -> int:
        return self.qt_app.exec()


def main() -> int:
    app = KeyDeckApplication()
    return app.run()
