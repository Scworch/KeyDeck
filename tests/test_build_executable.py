from __future__ import annotations

import unittest
from pathlib import Path

from scripts.build_executable import is_build_source_file


class BuildExecutableTests(unittest.TestCase):
    def test_plugin_code_is_not_included_in_release_build(self) -> None:
        self.assertFalse(
            is_build_source_file(Path("plugins") / "WQS" / "plugin.py")
        )
        self.assertFalse(
            is_build_source_file(
                Path("plugins") / "WaveLink" / "plugin.py"
            )
        )
        self.assertFalse(
            is_build_source_file(
                Path("plugins") / "ShortcutLauncher" / "manifest.json"
            )
        )

    def test_catalog_and_core_runtime_assets_remain_in_build(self) -> None:
        self.assertTrue(
            is_build_source_file(Path("plugins") / "catalog.json")
        )
        self.assertTrue(is_build_source_file(Path("keydeck") / "__main__.py"))
        self.assertTrue(is_build_source_file(Path("icons") / "settings.svg"))


if __name__ == "__main__":
    unittest.main()
