from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from keydeck.plugin_api import PluginContext
from plugins.MultiTool.plugin import Plugin, SequenceEditorDialog


class MultiToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plugin(self, invoke_slot=None) -> Plugin:
        context = PluginContext(
            plugin_id="MultiTool",
            plugin_name="MultiTool",
            plugin_dir=Path("."),
            entry_file=Path("plugin.py"),
            settings_file=Path("settings.json"),
            manifest={},
            invoke_assigned_slot=invoke_slot,
        )
        return Plugin(context)

    def test_sequence_runs_enabled_steps_in_order(self) -> None:
        plugin = self._plugin()
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary) / "example.exe"
            program.write_bytes(b"MZ example application")
            with patch("plugins.MultiTool.plugin.subprocess.Popen", side_effect=lambda *a, **k: calls.append("program")), patch(
                "plugins.MultiTool.plugin.webbrowser.open",
                side_effect=lambda url: calls.append(url) or True,
            ):
                plugin._run_sequence(
                    {
                        "steps": [
                            {"type": "program", "value": str(program)},
                            {"type": "url", "value": "https://example.com"},
                            {
                                "type": "program",
                                "value": "C:/skipped.exe",
                                "enabled": False,
                            },
                        ]
                    }
                )
        self.assertEqual(calls, ["program", "https://example.com"])

    def test_sequence_invokes_an_assigned_plugin_button(self) -> None:
        invoked: list[tuple[str, int]] = []
        plugin = self._plugin(lambda page_id, slot: invoked.append((page_id, slot)))

        plugin._run_sequence(
            {
                "steps": [
                    {
                        "type": "plugin",
                        "page_id": "page-id",
                        "slot": 3,
                    }
                ]
            }
        )

        self.assertEqual(invoked, [("page-id", 3)])

    def test_run_command_is_passed_as_data_not_shell_source(self) -> None:
        plugin = self._plugin()
        command = 'steam://run/123 "--option"'
        with patch("plugins.MultiTool.plugin.subprocess.Popen") as popen:
            plugin._run_windows_command(command)
        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["KEYDECK_RUN_COMMAND"], command)
        self.assertIn("-EncodedCommand", popen.call_args.args[0])

    def test_sequence_editor_reorders_and_persists_disabled_steps(self) -> None:
        dialog = SequenceEditorDialog(
            [
                {"type": "url", "value": "https://one.example", "enabled": True},
                {"type": "command", "value": "steam://run/1", "enabled": False},
            ],
            [],
        )
        try:
            dialog.step_list.setCurrentRow(1)
            dialog._move_selected(-1)

            steps = dialog.result_steps()

            self.assertEqual(steps[0]["type"], "command")
            self.assertFalse(steps[0]["enabled"])
            self.assertEqual(steps[1]["value"], "https://one.example")
            self.assertEqual(dialog.step_list.item(0).checkState(), Qt.CheckState.Unchecked)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
