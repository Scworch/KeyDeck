from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from plugins.NvidiaRtxVideoSuperResolution import vsr


class NvidiaVsrTests(unittest.TestCase):
    def test_nvcpl_candidates_include_both_program_files_roots(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ProgramW6432": r"C:\Apps64",
                "ProgramFiles": r"C:\Apps64",
                "ProgramFiles(x86)": r"C:\Apps32",
            },
            clear=True,
        ):
            candidates = vsr._nvcpl_candidates()

        self.assertEqual(len(candidates), 2)
        self.assertTrue(candidates[0].startswith(r"C:\Apps64"))
        self.assertTrue(candidates[1].startswith(r"C:\Apps32"))

    def test_missing_nvidia_app_explains_hardware_requirements(self) -> None:
        with patch("plugins.NvidiaRtxVideoSuperResolution.vsr.os.path.isfile", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "supported NVIDIA RTX GPU"):
                vsr._load_nvcpl()


if __name__ == "__main__":
    unittest.main()
