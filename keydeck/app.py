from __future__ import annotations

import sys

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

        self.deck_window = DeckWindow(
            settings=self.settings,
            actions=self.plugin_manager.all_actions(),
        )
        self.deck_window.settings_requested.connect(self._open_settings)
        self.deck_window.action_requested.connect(self._run_action)
        self.deck_window.blur_hide_requested.connect(self._hide_on_blur)

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

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.qt_app.quit)

        menu.addAction(toggle_action)
        menu.addAction(reload_action)
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

        painter.setBrush(QColor("#242424"))
        painter.setPen(QPen(QColor("#7a7a7a"), 2))
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#efefef"))
        cell = 12
        gap = 6
        start_x = 16
        start_y = 16
        for row in range(3):
            for col in range(3):
                x = start_x + col * (cell + gap)
                y = start_y + row * (cell + gap)
                painter.drawRoundedRect(x, y, cell, cell, 4, 4)

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
        if self.deck_window.isVisible():
            self.deck_window.hide()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.deck_window)
        if dialog.exec():
            self.settings = dialog.to_settings().clamp()
            save_settings(self.settings)
            self.deck_window.apply_settings(self.settings)

    def _run_action(self, action: Action | None) -> None:
        if action is None:
            return

        try:
            action.callback()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.deck_window, "Action Failed", str(exc))

    def reload_plugins(self) -> None:
        self.plugin_manager.load_plugins()
        self.deck_window.update_actions(self.plugin_manager.all_actions())

        if self.plugin_manager.errors:
            details = "\n".join(self.plugin_manager.errors)
            QMessageBox.warning(
                self.deck_window,
                "Plugin Loader",
                f"Some plugins failed to load:\n{details}",
            )

    def run(self) -> int:
        return self.qt_app.exec()


def main() -> int:
    app = KeyDeckApplication()
    return app.run()
