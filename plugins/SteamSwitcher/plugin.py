from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.append(str(PLUGIN_DIR))

import steam_switch  # noqa: E402


class Plugin(PluginBase):
    plugin_id = "SteamSwitcher"
    plugin_name = "SteamSwitcher"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        self._defaults = {
            "close_steam_before_switch": True,
            "launch_steam_after_switch": True,
        }
        if self.context is not None:
            self.context.save_settings(self._merged_settings())

    def actions(self) -> list[Action]:
        aliases: list[str] = []
        try:
            steam_path = steam_switch.get_steam_path()
            data = steam_switch.load_loginusers(steam_path / "config" / "loginusers.vdf")
            accounts = steam_switch.iter_remembered_user_records(data)
            for steam_id, record in accounts:
                acc_name = str(record.get("AccountName", "")).strip()
                if acc_name:
                    aliases.append(f"{self.plugin_id}.switch.{acc_name.lower()}")
        except Exception:
            pass

        return [
            Action(
                action_id=f"{self.plugin_id}.switch",
                title="Steam Switcher",
                callback=self._switch_account,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
                action_settings_callback=self._open_action_settings,
                action_icon_callback=self._get_action_icon,
                aliases=aliases,
            )
        ]

    def _get_action_icon(self, slot: int, current_settings: dict) -> str | None:
        account_name = current_settings.get("account_name")
        if not account_name:
            return None
            
        try:
            steam_path = steam_switch.get_steam_path()
            data = steam_switch.load_loginusers(steam_path / "config" / "loginusers.vdf")
            accounts = steam_switch.iter_remembered_user_records(data)
            for steam_id, record in accounts:
                rec_name = str(record.get("AccountName", "")).strip()
                if rec_name == account_name:
                    avatar_path = steam_switch.avatar_path_for_user(steam_path, steam_id, record)
                    return avatar_path
        except Exception:
            pass
        return None

    def _open_action_settings(self, slot: int, current_settings: dict) -> dict | None:
        try:
            steam_path = steam_switch.get_steam_path()
            data = steam_switch.load_loginusers(steam_path / "config" / "loginusers.vdf")
            accounts = steam_switch.iter_remembered_user_records(data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "SteamSwitcher", str(exc))
            return None

        if not accounts:
            QMessageBox.warning(None, "SteamSwitcher", "No remembered Steam accounts found.")
            return None

        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        dialog = QDialog(parent)
        dialog.setWindowTitle("Select Steam Account")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize, Qt

        list_widget = QListWidget(dialog)
        list_widget.setIconSize(QSize(32, 32))
        list_widget.itemDoubleClicked.connect(dialog.accept)
        
        selected_account = current_settings.get("account_name", "")
        
        for steam_id, record in accounts:
            account_name = str(record.get("AccountName", "")).strip()
            if not account_name:
                continue
            persona_name = str(record.get("PersonaName", "")).strip()
            avatar_path = steam_switch.avatar_path_for_user(steam_path, steam_id, record)

            title = account_name
            if not title and persona_name:
                title = persona_name
                
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, account_name)
            if avatar_path and Path(avatar_path).exists():
                item.setIcon(QIcon(avatar_path))
            list_widget.addItem(item)
            
            if account_name == selected_account:
                list_widget.setCurrentItem(item)

        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec():
            item = list_widget.currentItem()
            if item:
                return {"account_name": item.data(Qt.UserRole)}
        return None

    def open_settings(self) -> None:
        current = self._merged_settings()
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        dialog = QDialog(parent)
        dialog.setWindowTitle("SteamSwitcher Global Settings")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)

        close_steam_checkbox = QCheckBox("Close Steam before switch", dialog)
        close_steam_checkbox.setChecked(bool(current.get("close_steam_before_switch", True)))
        form.addRow(close_steam_checkbox)

        launch_steam_checkbox = QCheckBox("Launch Steam after switch", dialog)
        launch_steam_checkbox.setChecked(bool(current.get("launch_steam_after_switch", True)))
        form.addRow(launch_steam_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec():
            new_settings = {
                "close_steam_before_switch": close_steam_checkbox.isChecked(),
                "launch_steam_after_switch": launch_steam_checkbox.isChecked(),
            }
            self.context.save_settings(new_settings)

    def _switch_account_with_fallback(self, action_settings: dict, default_account: str) -> None:
        account_name = action_settings.get("account_name") or default_account
        if not account_name:
            QMessageBox.warning(None, "SteamSwitcher", "No account selected for this button. Right-click and choose 'Action Settings...'")
            return
            
        settings = self._merged_settings()
        steam_switch.switch_account(
            account_name=account_name,
            close_steam_before_switch=bool(settings.get("close_steam_before_switch", True)),
            launch_steam_after_switch=bool(settings.get("launch_steam_after_switch", True)),
        )

    def _switch_account(self, action_settings: dict) -> None:
        self._switch_account_with_fallback(action_settings, "")

    def _merged_settings(self) -> dict:
        if self.context is None:
            return dict(self._defaults)
        raw = self.context.load_settings(default=self._defaults)
        merged = dict(self._defaults)
        merged.update(raw)
        return merged
