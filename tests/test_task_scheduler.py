from __future__ import annotations

import getpass
import os
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from keydeck.app import KeyDeckApplication
from keydeck.config import AppSettings
from keydeck.ui.settings_dialog import SettingsDialog


TASK_NAMESPACE = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class TaskSchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_create_task_button_respects_auto_start_and_admin_selection(self) -> None:
        dialog = SettingsDialog(AppSettings(), [])
        requested: list[bool] = []
        dialog.autostart_task_requested.connect(requested.append)
        try:
            self.assertTrue(dialog.autostart_task_button.isEnabled())
            dialog.chk_run_as_admin.setChecked(True)
            dialog.autostart_task_button.click()
            self.assertEqual(requested, [True])

            dialog.chk_auto_start.setChecked(False)
            self.assertFalse(dialog.autostart_task_button.isEnabled())
            dialog.autostart_task_button.click()
            self.assertEqual(requested, [True])
        finally:
            dialog.close()

    def test_task_xml_targets_current_interactive_user_and_run_level(self) -> None:
        run_state = SimpleNamespace(_autostart_task_needs_retry=False)
        command = None

        def capture_task(command_args: list[str], **_kwargs) -> subprocess.CompletedProcess:
            nonlocal command
            command = command_args
            xml_path = Path(command_args[command_args.index("/XML") + 1])
            task = ET.parse(xml_path).getroot()
            principal = task.find(".//task:Principal", TASK_NAMESPACE)
            self.assertIsNotNone(principal)
            expected_username = os.environ.get("USERNAME") or getpass.getuser()
            expected_domain = os.environ.get("USERDOMAIN")
            expected_user_id = (
                f"{expected_domain}\\{expected_username}"
                if expected_domain
                else expected_username
            )
            self.assertEqual(
                principal.findtext("task:UserId", namespaces=TASK_NAMESPACE),
                expected_user_id,
            )
            self.assertEqual(
                principal.findtext("task:RunLevel", namespaces=TASK_NAMESPACE),
                "HighestAvailable",
            )
            return subprocess.CompletedProcess(command_args, 0, "", "")

        with patch("keydeck.app.sys.platform", "win32"), patch(
            "keydeck.app.subprocess.run",
            side_effect=capture_task,
        ):
            self.assertTrue(
                KeyDeckApplication._update_autostart_task(run_state, True, True)
            )

        self.assertIsNotNone(command)
        self.assertFalse(run_state._autostart_task_needs_retry)


if __name__ == "__main__":
    unittest.main()
