from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from keydeck.plugin_api import PluginContext
from plugins.ShortcutLauncher.plugin import Plugin, TargetPickerDialog, resolve_shortcut


class ShortcutLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_shortcut_target_is_copied_to_plugin_data_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Applications" / "Example.exe"
            source.parent.mkdir()
            source.write_bytes(b"MZ example application")
            context = PluginContext(
                plugin_id="ShortcutLauncher",
                plugin_name="Shortcut Launcher",
                plugin_dir=root / "plugin",
                entry_file=root / "plugin" / "plugin.py",
                settings_file=root / "data" / "settings.json",
                manifest={},
                data_dir=root / "data",
            )
            plugin = Plugin(context)

            copied = plugin._copy_shortcut_target(source)

            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_bytes(), source.read_bytes())
            self.assertEqual(copied.parent, root / "data" / "launch_targets")
            self.assertNotEqual(copied, source)

    def test_shortcut_resolution_keeps_arguments_and_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "Example.exe"
            shortcut = root / "Example.lnk"
            target.write_bytes(b"MZ example application")
            shortcut.write_bytes(b"shortcut")
            response = {
                "target": str(target),
                "arguments": "--profile default",
                "working_directory": str(root),
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
            with patch("plugins.ShortcutLauncher.plugin.subprocess.run", return_value=completed):
                resolved = resolve_shortcut(shortcut)

            self.assertEqual(resolved.target, target.resolve())
            self.assertEqual(resolved.arguments, "--profile default")
            self.assertEqual(resolved.working_directory, root)

    def test_shortcut_resolution_rejects_non_executable_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "document.txt"
            target.write_text("not an executable", encoding="utf-8")
            shortcut = root / "Document.lnk"
            shortcut.write_bytes(b"shortcut")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"target": str(target)}),
                stderr="",
            )
            with patch("plugins.ShortcutLauncher.plugin.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(ValueError, "existing .exe"):
                    resolve_shortcut(shortcut)

    def test_launch_action_runs_configured_command_or_deep_link(self) -> None:
        plugin = Plugin()
        command = 'steam://run/123 "--option"'
        with patch.object(plugin, "_run_windows_command") as run_command:
            plugin._launch({"launch_mode": "command", "command": command})

        run_command.assert_called_once_with(command)

    def test_command_is_passed_as_data_to_hidden_windows_run(self) -> None:
        plugin = Plugin()
        command = 'steam://run/123 "--option"'
        with patch("plugins.ShortcutLauncher.plugin.subprocess.Popen") as popen:
            plugin._run_windows_command(command)

        self.assertEqual(
            popen.call_args.kwargs["env"]["KEYDECK_RUN_COMMAND"],
            command,
        )
        self.assertIn("-EncodedCommand", popen.call_args.args[0])

    def test_target_picker_exposes_command_and_deep_link_mode(self) -> None:
        dialog = TargetPickerDialog("steam://run/123", "command")
        try:
            self.assertEqual(dialog.mode_combo.currentData(), "command")
            self.assertEqual(dialog.path_edit.text(), "steam://run/123")
            self.assertTrue(dialog.browse_button.isHidden())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
