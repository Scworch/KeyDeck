from __future__ import annotations

import unittest
from pathlib import Path

from scripts.build_executable import is_build_source_file


class BuildExecutableTests(unittest.TestCase):
    def test_wqs_sources_are_not_included_in_release_build(self) -> None:
        self.assertFalse(is_build_source_file(Path("plugins") / "WQS" / "plugin.py"))
        self.assertFalse(
            is_build_source_file(
                Path("plugins") / "WQS" / "icons" / "headphones.svg"
            )
        )

    def test_other_plugins_and_runtime_assets_remain_in_build(self) -> None:
        self.assertTrue(
            is_build_source_file(Path("plugins") / "WaveLink" / "plugin.py")
        )
        self.assertTrue(is_build_source_file(Path("keydeck") / "__main__.py"))
        self.assertTrue(is_build_source_file(Path("icons") / "settings.svg"))


if __name__ == "__main__":
    unittest.main()
