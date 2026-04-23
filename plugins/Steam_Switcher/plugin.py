from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QMessageBox, QVBoxLayout

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
        try:
            steam_path = steam_switch.get_steam_path()
            data = steam_switch.load_loginusers(steam_path / "config" / "loginusers.vdf")
            accounts = steam_switch.iter_remembered_user_records(data)
        except Exception as exc:  # noqa: BLE001
            return [
                Action(
                    action_id=f"{self.plugin_id}.error",
                    title="Steam: error",
                    callback=lambda: QMessageBox.critical(None, "SteamSwitcher", str(exc)),
                    plugin_id=self.plugin_id,
                    settings_callback=self.open_settings,
                )
            ]

        if not accounts:
            return [
                Action(
                    action_id=f"{self.plugin_id}.no_accounts",
                    title="Steam: no accounts",
                    callback=lambda: QMessageBox.warning(
                        None,
                        "SteamSwitcher",
                        "No remembered Steam accounts found.",
                    ),
                    plugin_id=self.plugin_id,
                    settings_callback=self.open_settings,
                )
            ]

        actions: list[Action] = []
        for steam_id, record in accounts:
            account_name = str(record.get("AccountName", "")).strip()
            if not account_name:
                continue
            persona_name = str(record.get("PersonaName", "")).strip()
            avatar_path = steam_switch.avatar_path_for_user(steam_path, steam_id, record)

            title = account_name
            if not title and persona_name:
                title = persona_name
            actions.append(
                Action(
                    action_id=f"{self.plugin_id}.switch.{account_name.lower()}",
                    title=title,
                    callback=lambda acc=account_name: self._switch_account(acc),
                    plugin_id=self.plugin_id,
                    settings_callback=self.open_settings,
                    icon_path=avatar_path,
                )
            )
        return actions

    def open_settings(self) -> None:
        if self.context is None:
            return

        current = self._merged_settings()
        dialog = QDialog()
        dialog.setWindowTitle("SteamSwitcher settings")
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

    def _switch_account(self, account_name: str) -> None:
        settings = self._merged_settings()
        steam_switch.switch_account(
            account_name=account_name,
            close_steam_before_switch=bool(settings.get("close_steam_before_switch", True)),
            launch_steam_after_switch=bool(settings.get("launch_steam_after_switch", True)),
        )

    def _merged_settings(self) -> dict:
        if self.context is None:
            return dict(self._defaults)
        raw = self.context.load_settings(default=self._defaults)
        merged = dict(self._defaults)
        merged.update(raw)
        return merged
