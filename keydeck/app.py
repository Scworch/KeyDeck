from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from keydeck.config import ICONS_DIR, PLUGINS_DIR, AppSettings, load_settings, save_settings
from keydeck.plugin_api import Action
from keydeck.plugin_manager import PluginManager
from keydeck.ui.deck_window import DeckWindow
from keydeck.ui.settings_dialog import SettingsDialog


class KeyDeckApplication(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName("KeyDeck")
        self.qt_app.setQuitOnLastWindowClosed(False)

        self.settings: AppSettings = load_settings()
        self.plugin_manager = PluginManager(PLUGINS_DIR)
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
        self.deck_window.blur_hide_requested.connect(self._hide_on_blur)

        self._is_settings_open = False
        self.tray_icon = self._create_tray()
        self.tray_icon.show()

    def _create_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self._load_tray_icon(), self.qt_app)
        tray.setToolTip("KeyDeck")
        tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        toggle_action = QAction("Show / Hide Deck", menu)
        toggle_action.triggered.connect(self.toggle_window)

        reload_action = QAction("Reload Plugins", menu)
        reload_action.triggered.connect(self.reload_plugins)

        restart_action = QAction("Restart", menu)
        restart_action.triggered.connect(self.restart_application)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.qt_app.quit)

        menu.addAction(toggle_action)
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
                self.settings = dialog.to_settings().clamp()
                save_settings(self.settings)
                self.deck_window.update_actions(dialog.actions)
                self.deck_window.apply_settings(self.settings)
        finally:
            self._is_settings_open = False


    def _run_action(self, action: Action | None) -> None:
        if action is None:
            return

        try:
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
        subprocess.Popen(
            [sys.executable, "-m", "keydeck"],
            cwd=str(Path(__file__).resolve().parent.parent),
            close_fds=True,
        )
        self.qt_app.quit()

    def run(self) -> int:
        return self.qt_app.exec()


def main() -> int:
    app = KeyDeckApplication()
    return app.run()
