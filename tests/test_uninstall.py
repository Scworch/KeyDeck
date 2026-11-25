from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keydeck import uninstall


class UninstallTests(unittest.TestCase):
    def test_uninstaller_removes_executable_and_keeps_user_data_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper_dir = root / "temp"
            helper_dir.mkdir()
            helper = helper_dir / "KeyDeckUninstaller-test.exe"
            helper.write_bytes(b"helper")
            executable = root / "KeyDeck.exe"
            executable.write_bytes(b"application")
            app_data = root / "KeyDeck"
            app_data.mkdir()
            (app_data / "settings.json").write_text("{}", encoding="utf-8")

            with (
                patch("keydeck.uninstall.sys.argv", [str(helper)]),
                patch("keydeck.uninstall.tempfile.gettempdir", return_value=str(helper_dir)),
                patch("keydeck.uninstall.wait_for_process_exit"),
                patch("keydeck.uninstall._remove_startup_task_and_shortcuts") as cleanup,
                patch("keydeck.uninstall.APP_DATA_DIR", app_data),
                patch("keydeck.uninstall.sys.platform", "win32"),
                patch("keydeck.uninstall._show_uninstall_message") as show_message,
            ):
                result = uninstall.run_uninstaller([str(executable), "1234", "1"])

            self.assertEqual(result, 0)
            self.assertFalse(executable.exists())
            self.assertFalse(helper.exists())
            self.assertTrue((app_data / "settings.json").is_file())
            cleanup.assert_called_once_with(executable.resolve())
            show_message.assert_called_once()

    def test_remove_user_data_requires_keydeck_directory_inside_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_data = root / "KeyDeck"
            app_data.mkdir()
            (app_data / "settings.json").write_text("{}", encoding="utf-8")
            outside_data = root / "OtherApp"
            outside_data.mkdir()
            (outside_data / "keep.txt").write_text("keep", encoding="utf-8")

            with (
                patch("keydeck.uninstall.os.environ", {**os.environ, "LOCALAPPDATA": str(root)}),
                patch("keydeck.uninstall.APP_DATA_DIR", outside_data),
            ):
                with self.assertRaisesRegex(ValueError, "outside the KeyDeck"):
                    uninstall._remove_user_data()

            self.assertTrue((outside_data / "keep.txt").is_file())
            self.assertTrue((app_data / "settings.json").is_file())

    def test_uninstaller_removes_user_data_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper_dir = root / "temp"
            helper_dir.mkdir()
            helper = helper_dir / "KeyDeckUninstaller-remove.exe"
            helper.write_bytes(b"helper")
            executable = root / "KeyDeck.exe"
            executable.write_bytes(b"application")
            app_data = root / "KeyDeck"
            app_data.mkdir()
            (app_data / "plugins").mkdir()
            (app_data / "plugins" / "settings.json").write_text("{}", encoding="utf-8")

            with (
                patch("keydeck.uninstall.sys.argv", [str(helper)]),
                patch("keydeck.uninstall.tempfile.gettempdir", return_value=str(helper_dir)),
                patch("keydeck.uninstall.wait_for_process_exit"),
                patch("keydeck.uninstall._remove_startup_task_and_shortcuts"),
                patch("keydeck.uninstall.APP_DATA_DIR", app_data),
                patch("keydeck.uninstall.os.environ", {**os.environ, "LOCALAPPDATA": str(root)}),
                patch("keydeck.uninstall.sys.platform", "win32"),
                patch("keydeck.uninstall._show_uninstall_message"),
            ):
                result = uninstall.run_uninstaller([str(executable), "1234", "0"])

            self.assertEqual(result, 0)
            self.assertFalse(executable.exists())
            self.assertFalse(app_data.exists())

    def test_remove_user_data_refuses_reparse_points(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_data = root / "KeyDeck"
            app_data.mkdir()
            (app_data / "settings.json").write_text("{}", encoding="utf-8")

            with (
                patch("keydeck.uninstall.os.environ", {**os.environ, "LOCALAPPDATA": str(root)}),
                patch("keydeck.uninstall.APP_DATA_DIR", app_data),
                patch("keydeck.uninstall._is_reparse_point", return_value=True),
            ):
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    uninstall._remove_user_data()

            self.assertTrue((app_data / "settings.json").is_file())


if __name__ == "__main__":
    unittest.main()
