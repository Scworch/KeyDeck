from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QInputDialog

from keydeck.plugin_api import PluginContext
from plugins.MultiTool.plugin import Plugin, SequenceEditorDialog, SequenceStepCard


class MultiToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plugin(self, invoke_slot=None, invoke_action=None) -> Plugin:
        context = PluginContext(
            plugin_id="MultiTool",
            plugin_name="MultiTool",
            plugin_dir=Path("."),
            entry_file=Path("plugin.py"),
            settings_file=Path("settings.json"),
            manifest={},
            invoke_assigned_slot=invoke_slot,
            invoke_plugin_action=invoke_action,
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

    def test_sequence_invokes_any_plugin_action_with_its_own_settings(self) -> None:
        invoked: list[tuple[str, dict]] = []
        plugin = self._plugin(
            invoke_action=lambda action_id, settings: invoked.append(
                (action_id, settings)
            )
        )

        plugin._execute_step(
            {
                "type": "plugin_action",
                "action_id": "SteamLauncher.launch",
                "settings": {"profile_id": "work"},
            }
        )

        self.assertEqual(
            invoked,
            [("SteamLauncher.launch", {"profile_id": "work"})],
        )

    def test_sequence_waits_between_actions_without_blocking(self) -> None:
        plugin = self._plugin()
        calls: list[float] = []
        started = time.monotonic()
        loop = QEventLoop()

        with patch(
            "plugins.MultiTool.plugin.webbrowser.open",
            side_effect=lambda _url: calls.append(time.monotonic()) or True,
        ):
            plugin._run_sequence(
                {
                    "steps": [
                        {"type": "url", "value": "https://first.example"},
                        {"type": "delay", "milliseconds": 30},
                        {"type": "url", "value": "https://second.example"},
                    ]
                }
            )

            def finish_when_done() -> None:
                if plugin._sequence_running:
                    QTimer.singleShot(5, finish_when_done)
                else:
                    loop.quit()

            QTimer.singleShot(5, finish_when_done)
            QTimer.singleShot(1000, loop.quit)
            loop.exec()

        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(calls[1] - calls[0], 0.02)
        self.assertGreaterEqual(calls[0], started)

    def test_invalid_saved_delay_uses_safe_editor_default(self) -> None:
        dialog = SequenceEditorDialog([], [])
        try:
            with patch.object(QInputDialog, "getInt", return_value=(200, True)) as get_int:
                dialog._add_step("delay", {"milliseconds": "invalid"})

            self.assertEqual(
                get_int.call_args.args[3],
                1000,
            )
            self.assertEqual(
                dialog.result_steps(),
                [{"type": "delay", "milliseconds": 200, "enabled": True}],
            )
        finally:
            dialog.close()

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
            card = dialog.step_list.itemWidget(dialog.step_list.item(0))
            self.assertIsInstance(card, SequenceStepCard)
            self.assertEqual(
                card.findChild(QLabel, "SequenceStepNumber").text(),
                "01",
            )
        finally:
            dialog.close()

    def test_step_card_toggle_controls_whether_action_runs(self) -> None:
        dialog = SequenceEditorDialog(
            [{"type": "url", "value": "https://example.com"}],
            [],
        )
        try:
            card = dialog.step_list.itemWidget(dialog.step_list.item(0))

            card.enabled_toggle.click()

            self.assertFalse(dialog.result_steps()[0]["enabled"])
        finally:
            dialog.close()

    def test_multitool_action_does_not_offer_json_plugin_settings(self) -> None:
        action = self._plugin().actions()[0]

        self.assertFalse(action.plugin_settings_enabled)
        self.assertIsNone(action.settings_callback)


if __name__ == "__main__":
    unittest.main()
