from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.package_plugin_release import package_plugin_release


class PluginReleasePackagingTests(unittest.TestCase):
    def test_release_archive_contains_plugin_code_without_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path, checksum_path = package_plugin_release(
                "plugin-MultiTool-v0.2.0",
                Path(temporary),
            )

            self.assertTrue(checksum_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())

            self.assertIn("manifest.json", names)
            self.assertIn("plugin.py", names)
            self.assertFalse(any("settings" in name.casefold() for name in names))
            self.assertFalse(any("cache" in name.casefold() for name in names))

    def test_release_tag_must_match_catalog_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "current catalog"):
                package_plugin_release(
                    "plugin-MultiTool-v9.9.9",
                    Path(temporary),
                )


if __name__ == "__main__":
    unittest.main()
