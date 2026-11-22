from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILE = ROOT / "plugins" / "SteamLauncher" / "plugin.py"
SPEC = importlib.util.spec_from_file_location("steam_launcher_plugin_test", PLUGIN_FILE)
assert SPEC is not None and SPEC.loader is not None
steam_launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steam_launcher
SPEC.loader.exec_module(steam_launcher)


class SteamLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_action_callback_uses_captured_profile_not_slot_settings(self) -> None:
        plugin = steam_launcher.Plugin()
        with patch.object(plugin, "_resolve_game_icon", return_value=None):
            action = plugin.actions()[0]

        with patch.object(plugin, "_launch") as launch:
            action.callback({"account_name": "not a profile"})

        launch.assert_called_once_with(plugin._profiles[0])

    def test_missing_icons_are_resolved_without_blocking_for_network(self) -> None:
        plugin = steam_launcher.Plugin()
        with patch.object(plugin, "_fetch_client_icon_hash", side_effect=AssertionError):
            with patch.object(plugin, "_queue_icon_fetch") as queue_fetch:
                self.assertIsNone(plugin._resolve_game_icon("987654321"))
        queue_fetch.assert_called_once_with("987654321")

    def test_editing_title_keeps_spaces_cursor_and_selected_profile(self) -> None:
        profiles = [
            steam_launcher.LaunchProfile("one", "First", "730"),
            steam_launcher.LaunchProfile("two", "Second", "570"),
        ]
        dialog = steam_launcher.SettingsDialog(profiles, lambda _steam_id: None)
        try:
            dialog.list_widget.setCurrentRow(1)
            dialog.title_edit.setFocus()
            dialog.title_edit.setCursorPosition(0)
            QTest.keyClick(dialog.title_edit, Qt.Key_Space)

            self.assertEqual(dialog.title_edit.text(), " Second")
            self.assertEqual(dialog.title_edit.cursorPosition(), 1)
            self.assertEqual(dialog.list_widget.currentRow(), 1)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
