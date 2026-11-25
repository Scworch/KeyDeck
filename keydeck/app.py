from __future__ import annotations

import getpass
import http.client
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from keydeck import __version__
from keydeck.admin import is_admin, restart_as_admin
from keydeck.config import (
    ICONS_DIR,
    INSTALLED_PLUGINS_DIR,
    PLUGINS_DIR,
    PLUGIN_BACKUP_DIR,
    PLUGIN_DATA_DIR,
    AppSettings,
    load_settings,
    save_settings,
)
from keydeck.plugin_api import Action, PluginBase
from keydeck.plugin_manager import PluginInfo, PluginManager
from keydeck.plugin_store import PluginStore
from keydeck.uninstall import launch_uninstaller
from keydeck.updates import (
    Release,
    UpdateCancelled,
    check_latest_release,
    download_release,
    launch_update_helper,
    update_check_due,
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
    plugin_actions_refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.plugin_actions_refresh_requested.connect(self._refresh_plugin_actions)
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName("KeyDeck")
        self.qt_app.setQuitOnLastWindowClosed(False)
        app_icon_path = ICONS_DIR / "keydeck.ico"
        self.app_icon = QIcon(str(app_icon_path)) if app_icon_path.is_file() else QIcon()
        if not self.app_icon.isNull():
            self.qt_app.setWindowIcon(self.app_icon)
        apply_dark_theme(self.qt_app)

        self.settings: AppSettings = load_settings()
        self._action_invocation_stack: list[tuple[str, int]] = []
        self.plugin_store = PluginStore(
            INSTALLED_PLUGINS_DIR,
            PLUGIN_BACKUP_DIR,
            PLUGINS_DIR / "catalog.json",
        )
        legacy_plugins_dir = (
            Path(sys.executable).resolve().parent / "plugins"
            if getattr(sys, "frozen", False)
            else None
        )
        self.plugin_manager = PluginManager(
            PLUGINS_DIR,
            additional_plugins_dirs=(INSTALLED_PLUGINS_DIR,),
            data_dir=PLUGIN_DATA_DIR,
            legacy_data_dir=legacy_plugins_dir,
            get_assigned_slots=self._assigned_plugin_slots,
            invoke_assigned_slot=self._invoke_assigned_plugin_slot,
            refresh_actions=self.plugin_actions_refresh_requested.emit,
        )
        self.plugin_manager.load_plugins(set(self.settings.disabled_plugins))
        self.plugin_manager.start_plugins()
        self.qt_app.aboutToQuit.connect(self.plugin_manager.unload_plugins)
        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=True)


        self.deck_window = DeckWindow(
            settings=self.settings,
            actions=actions,
        )
        if not self.app_icon.isNull():
            self.deck_window.setWindowIcon(self.app_icon)
        self.deck_window.settings_requested.connect(self._open_settings)
        self.deck_window.action_requested.connect(self._run_action)
        self.deck_window.page_changed.connect(self._on_page_changed)
        self.deck_window.blur_hide_requested.connect(self._hide_on_blur)

        from keydeck.hotkey_manager import HotkeyManager

        self._is_settings_open = False
        self._settings_dialog: SettingsDialog | None = None
        self._update_worker: UpdateWorker | None = None
        self._manual_update_check = False
        self._update_check_from_settings = False
        self._available_release: Release | None = None
        self._retry_autostart = "--retry-autostart" in sys.argv
        self._autostart_task_needs_retry = False
        self.tray_icon = self._create_tray()
        self.tray_icon.show()
        QTimer.singleShot(5000, self._notify_missing_plugin_code)
        self.qt_app.aboutToQuit.connect(self._stop_update_worker)
        QTimer.singleShot(2500, self._check_updates_if_due)
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(24 * 60 * 60 * 1000)
        self._update_check_timer.timeout.connect(self._check_updates_if_due)
        self._update_check_timer.start()
        if self._retry_autostart:
            QTimer.singleShot(1000, self._retry_autostart_task)

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

    def _notify_missing_plugin_code(self) -> None:
        installed_ids = {
            plugin.plugin_id for plugin in self.plugin_manager.discover_plugins()
        }
        try:
            catalog = self.plugin_store.bundled_catalog()
        except (OSError, ValueError) as exc:
            self.plugin_manager.errors.append(f"Plugin catalog unavailable: {exc}")
            catalog = []
        plugin_names = {entry.plugin_id: entry.name for entry in catalog}
        action_prefixes = {
            prefix: entry.plugin_id
            for entry in catalog
            for prefix in entry.action_prefixes
        }
        missing_plugins: dict[str, str] = {}
        for page in self.settings.pages:
            for action_id in page.slot_actions:
                if not action_id or "." not in action_id:
                    continue
                prefix = action_id.split(".", 1)[0]
                if prefix == "core":
                    continue
                plugin_id = action_prefixes.get(prefix, prefix)
                if plugin_id not in installed_ids:
                    missing_plugins[plugin_id] = plugin_names.get(plugin_id, plugin_id)
        missing_names = sorted(missing_plugins.values())
        if missing_names:
            displayed_names = ", ".join(missing_names[:5])
            if len(missing_names) > 5:
                displayed_names += f", and {len(missing_names) - 5} more"
            self.tray_icon.showMessage(
                "Plugin installation required",
                f"Install missing plugins ({displayed_names}) from Settings > Plugins > Plugin Library.",
                QSystemTrayIcon.Warning,
            )

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
                refresh_actions_callback=self._current_plugin_actions,
                available_plugins=self.plugin_manager.discover_plugins(),
                plugin_store=self.plugin_store,
                plugin_library_before_mutation=self._suspend_plugins_for_library_change,
                source_plugin_ids=(
                    {
                        plugin.plugin_id
                        for plugin in self.plugin_manager.discover_plugins()
                    }
                    if not getattr(sys, "frozen", False)
                    else set()
                ),
            )
            dialog.actions_changed.connect(self._settings_actions_changed)
            dialog.update_check_requested.connect(self._check_updates_from_settings)
            dialog.update_install_requested.connect(self._install_update_from_settings)
            dialog.autostart_task_requested.connect(self._register_autostart_task)
            self._settings_dialog = dialog

            if dialog.exec():
                if dialog.uninstall_preserve_user_data is not None:
                    try:
                        launch_uninstaller(
                            Path(sys.executable),
                            os.getpid(),
                            preserve_user_data=dialog.uninstall_preserve_user_data,
                        )
                    except (OSError, RuntimeError, ValueError) as exc:
                        QMessageBox.critical(
                            self.deck_window,
                            "Uninstall KeyDeck",
                            f"Could not start the uninstaller:\n\n{exc}",
                        )
                    else:
                        self.qt_app.quit()
                    return
                new_settings = dialog.to_settings().clamp()
                task_changed = (
                    self._autostart_task_needs_retry
                    or self.settings.auto_start != new_settings.auto_start
                    or (
                        new_settings.auto_start
                        and self.settings.run_as_admin != new_settings.run_as_admin
                    )
                )
                plugins_changed = (
                    set(new_settings.disabled_plugins)
                    != set(self.plugin_manager.disabled_plugin_ids)
                )
                if plugins_changed:
                    dialog.release_plugin_references()
                    self._clear_deck_plugin_references()
                    self.settings = new_settings
                    self.plugin_manager.load_plugins(set(self.settings.disabled_plugins))
                    self.plugin_manager.start_plugins()
                    actions = self.plugin_manager.all_actions()
                else:
                    self.settings = new_settings
                    actions = dialog.actions
                self._normalize_settings_actions(
                    actions,
                    persist=False,
                    disabled_plugin_ids=set(self.settings.disabled_plugins),
                )
                save_settings(self.settings)
                if task_changed:
                    self._update_autostart_task(
                        self.settings.auto_start,
                        self.settings.run_as_admin,
                    )
                self.deck_window.update_actions(actions)
                self.deck_window.apply_settings(self.settings)
                self.hotkey_manager.apply_hotkeys(
                    self.settings.slot_hotkeys,
                    self.settings.right_alt_toggle,
                )
                if plugins_changed and self.plugin_manager.errors:
                    QMessageBox.warning(
                        self.deck_window,
                        "Plugin Loader",
                        "Some plugins failed to load:\n"
                        + "\n".join(self.plugin_manager.errors),
                    )
            elif set(self.plugin_manager.disabled_plugin_ids) != set(
                self.settings.disabled_plugins
            ):
                dialog.release_plugin_references()
                self._clear_deck_plugin_references()
                self.plugin_manager.load_plugins(set(self.settings.disabled_plugins))
                self.plugin_manager.start_plugins()
                actions = self.plugin_manager.all_actions()
                self._normalize_settings_actions(
                    actions,
                    persist=False,
                    disabled_plugin_ids=set(self.settings.disabled_plugins),
                )
                self.deck_window.update_actions(actions)
                self.deck_window.apply_settings(self.settings)
        finally:
            self._settings_dialog = None
            self._is_settings_open = False

    def _update_autostart_task(
        self,
        enable: bool,
        run_as_admin: bool = False,
        offer_admin_restart: bool = True,
    ) -> bool:
        if sys.platform != "win32":
            return True
        temp_xml: str | None = None
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
                username = os.environ.get("USERNAME") or getpass.getuser()
                domain = os.environ.get("USERDOMAIN")
                user_id = f"{domain}\\{username}" if domain else username
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
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>{"HighestAvailable" if run_as_admin else "LeastPrivilege"}</RunLevel>
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
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.run(
                    ["schtasks", "/Delete", "/TN", "KeyDeck_AutoStart", "/F"],
                    check=True,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            self._autostart_task_needs_retry = False
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            self._autostart_task_needs_retry = True
            details = ""
            if isinstance(exc, subprocess.CalledProcessError):
                details = (exc.stderr or exc.stdout or "").strip()
            message = f"Could not update the Windows Task Scheduler task: {exc}"
            if details:
                message = f"{message}\n\n{details}"
            if offer_admin_restart and not is_admin():
                prompt = QMessageBox(self.deck_window)
                prompt.setIcon(QMessageBox.Warning)
                prompt.setWindowTitle("Task Scheduler")
                prompt.setText(message)
                prompt.setInformativeText(
                    "Windows may require administrator privileges to register this task."
                )
                restart_button = prompt.addButton(
                    "Restart as administrator",
                    QMessageBox.AcceptRole,
                )
                prompt.addButton(QMessageBox.Cancel)
                prompt.exec()
                if prompt.clickedButton() == restart_button:
                    if restart_as_admin(["--retry-autostart"]):
                        self.qt_app.quit()
            else:
                QMessageBox.critical(self.deck_window, "Task Scheduler", message)
            return False
        finally:
            if temp_xml is not None:
                Path(temp_xml).unlink(missing_ok=True)

    def _register_autostart_task(self, run_as_admin: bool) -> None:
        self.settings.auto_start = True
        self.settings.run_as_admin = bool(run_as_admin)
        save_settings(self.settings)
        if self._update_autostart_task(True, self.settings.run_as_admin):
            self.tray_icon.showMessage(
                "Task Scheduler",
                "KeyDeck startup task was created or updated.",
                QSystemTrayIcon.Information,
            )

    def _retry_autostart_task(self) -> None:
        success = self._update_autostart_task(
            self.settings.auto_start,
            self.settings.run_as_admin,
            offer_admin_restart=False,
        )
        if success:
            self.tray_icon.showMessage(
                "Task Scheduler",
                "KeyDeck startup task was updated.",
                QSystemTrayIcon.Information,
            )

    def _check_updates_if_due(self) -> None:
        if update_check_due(self.settings.last_update_check):
            self.check_for_updates()


    def _run_action(
        self,
        action: Action | None,
        slot: int = -1,
        page_index: int = 0,
        propagate_errors: bool = False,
    ) -> None:
        if action is None:
            return

        invocation_key: tuple[str, int] | None = None
        if 0 <= page_index < len(self.settings.pages) and slot >= 0:
            invocation_key = (self.settings.pages[page_index].page_id, slot)
            if invocation_key in self._action_invocation_stack:
                if propagate_errors:
                    raise RuntimeError("Multi-tool action loop detected")
                QMessageBox.warning(
                    self.deck_window,
                    "Action loop",
                    "This action is already running in the current multi-tool sequence.",
                )
                return
            self._action_invocation_stack.append(invocation_key)

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
            if propagate_errors:
                raise
            QMessageBox.critical(self.deck_window, "Action Failed", str(exc))
            return
        finally:
            if invocation_key is not None:
                self._action_invocation_stack.pop()

        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=True)
        self.deck_window.update_actions(actions)

    def reload_plugins(self) -> None:
        self._clear_deck_plugin_references()
        self.plugin_manager.load_plugins(set(self.settings.disabled_plugins))
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

    def _settings_actions_changed(self, actions: list[Action]) -> None:
        self.deck_window.update_actions(actions)
        self.deck_window.apply_settings(self.settings)

    def _refresh_plugin_actions(self) -> None:
        if not hasattr(self, "deck_window"):
            return
        settings_dialog = getattr(self, "_settings_dialog", None)
        if settings_dialog is not None and settings_dialog.isVisible():
            settings_dialog._refresh_plugin_actions()
            return
        actions = self._current_plugin_actions()
        self.deck_window.update_actions(actions)

    def _assigned_plugin_slots(self) -> list[dict]:
        actions_by_id = {
            action.action_id: action
            for action in self.plugin_manager.all_actions()
        }
        slots: list[dict] = []
        for page_index, page in enumerate(self.settings.pages):
            for slot, action_id in enumerate(page.slot_actions):
                action = actions_by_id.get(action_id) if action_id else None
                if action is None or action.plugin_id == "core":
                    continue
                slots.append(
                    {
                        "page_id": page.page_id,
                        "page_name": page.name,
                        "page_index": page_index,
                        "slot": slot,
                        "action_id": action.action_id,
                        "title": action.title,
                        "plugin_id": action.plugin_id,
                    }
                )
        return slots

    def _invoke_assigned_plugin_slot(self, page_id: str, slot: int) -> None:
        page_index = next(
            (
                index
                for index, page in enumerate(self.settings.pages)
                if page.page_id == page_id
            ),
            None,
        )
        if page_index is None:
            raise ValueError("The selected plugin button page no longer exists")
        page = self.settings.pages[page_index]
        if not 0 <= slot < len(page.slot_actions):
            raise ValueError("The selected plugin button no longer exists")
        action_id = page.slot_actions[slot]
        action = next(
            (
                item
                for item in self.deck_window.actions
                if item.action_id == action_id
            ),
            None,
        )
        if action is None or action.plugin_id == "core":
            raise ValueError("The selected plugin button action is unavailable")
        if (page_id, slot) in self._action_invocation_stack:
            raise RuntimeError("Multi-tool action loop detected")
        self._run_action(action, slot, page_index, propagate_errors=True)

    def _clear_deck_plugin_references(self) -> None:
        self.deck_window.update_actions([])
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _current_plugin_actions(self) -> list[Action]:
        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(actions, persist=False)
        return actions

    def _load_plugins_for_settings(
        self,
        disabled_plugin_ids: set[str],
    ) -> tuple[list[Action], list[PluginBase], list[str], list[PluginInfo]]:
        self._clear_deck_plugin_references()
        self.plugin_manager.load_plugins(disabled_plugin_ids)
        self.plugin_manager.start_plugins()
        actions = self.plugin_manager.all_actions()
        self._normalize_settings_actions(
            actions,
            persist=False,
            disabled_plugin_ids=disabled_plugin_ids,
        )
        return (
            actions,
            self.plugin_manager.get_plugins(),
            list(self.plugin_manager.errors),
            self.plugin_manager.discover_plugins(),
        )

    def _suspend_plugins_for_library_change(self) -> None:
        self._clear_deck_plugin_references()
        self.plugin_manager.unload_plugins()

    def _normalize_settings_actions(
        self,
        actions: list[Action],
        persist: bool,
        disabled_plugin_ids: set[str] | None = None,
    ) -> None:
        valid_action_ids = {action.action_id for action in actions}
        aliases: dict[str, str] = {}
        for action in actions:
            for alias in action.aliases:
                aliases[str(alias)] = action.action_id
        preserved_plugin_ids = set(
            disabled_plugin_ids
            if disabled_plugin_ids is not None
            else self.settings.disabled_plugins
        )
        for page in self.settings.pages:
            for action_id in page.slot_actions:
                if action_id and "." in action_id:
                    plugin_id = action_id.split(".", 1)[0]
                    if plugin_id != "core":
                        preserved_plugin_ids.add(plugin_id)
        if self.settings.normalize_action_ids(
            valid_action_ids,
            aliases,
            preserved_plugin_ids,
        ) and persist:
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

    def check_for_updates(
        self,
        manual: bool = False,
        from_settings: bool = False,
    ) -> None:
        if not manual and not update_check_due(self.settings.last_update_check):
            return
        if self._update_worker is not None and self._update_worker.isRunning():
            self._manual_update_check = manual
            self._update_check_from_settings = from_settings
            return
        self._manual_update_check = manual
        self._update_check_from_settings = from_settings
        self.settings.last_update_check = time.time()
        save_settings(self.settings)
        if from_settings and self._settings_dialog is not None:
            self._settings_dialog.set_update_status("Checking for updates...")
        worker = UpdateWorker()
        worker.checked.connect(self._on_update_checked)
        worker.failed.connect(self._on_update_check_failed)
        worker.finished.connect(self._on_update_worker_finished)
        self._update_worker = worker
        worker.start()

    def _check_updates_from_settings(self) -> None:
        self.check_for_updates(manual=True, from_settings=True)

    def _install_update_from_settings(self) -> None:
        release = self._available_release
        if release is None or (
            self._update_worker is not None and self._update_worker.isRunning()
        ):
            return
        if not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        self._update_check_from_settings = True
        if self._settings_dialog is not None:
            self._settings_dialog.set_update_status(
                f"Downloading and verifying KeyDeck {release.version}...",
                available_version=release.version,
            )
        self._start_update_download(release)

    def _start_update_download(self, release: Release) -> None:
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

    def _on_update_checked(self, release: Release | None) -> None:
        if release is None:
            self._available_release = None
            if self._update_check_from_settings and self._settings_dialog is not None:
                self._settings_dialog.set_update_status(
                    f"KeyDeck {__version__} is up to date."
                )
                return
            if self._manual_update_check:
                QMessageBox.information(
                    self.deck_window,
                    "KeyDeck updates",
                    f"KeyDeck {__version__} is up to date.",
                )
            return

        self._available_release = release
        if self._update_check_from_settings and self._settings_dialog is not None:
            self._settings_dialog.set_update_status(
                f"KeyDeck {release.version} is available to install.",
                available_version=release.version,
                install_enabled=True,
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

        self._start_update_download(release)

    def _on_update_check_failed(self, error: str) -> None:
        message = f"Could not check for updates: {error}"
        if self._update_check_from_settings and self._settings_dialog is not None:
            self._settings_dialog.set_update_status(message)
            return
        if self._manual_update_check:
            QMessageBox.warning(self.deck_window, "KeyDeck updates", message)
        else:
            self.tray_icon.showMessage(
                "KeyDeck updates",
                message,
                QSystemTrayIcon.Warning,
            )

    def _on_update_download_failed(self, error: str) -> None:
        release = self._available_release
        if self._update_check_from_settings and self._settings_dialog is not None:
            self._settings_dialog.set_update_status(
                f"Download failed: {error}",
                available_version=release.version if release is not None else None,
                install_enabled=release is not None,
            )
            return
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
