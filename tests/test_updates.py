from __future__ import annotations

import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from keydeck.config import AppSettings
from keydeck.updates import (
    Release,
    _is_github_url,
    apply_update,
    download_release,
    is_newer_version,
    update_check_due,
)


class UpdateTests(unittest.TestCase):
    def test_version_comparison_accepts_release_tags(self) -> None:
        self.assertTrue(is_newer_version("v0.2.0", "0.1.0"))
        self.assertFalse(is_newer_version("0.1.0", "0.1.0"))
        self.assertFalse(is_newer_version("0.0.9", "0.1.0"))

    def test_automatic_update_checks_are_limited_to_24_hours(self) -> None:
        day = 24 * 60 * 60
        self.assertTrue(update_check_due(0, now=day))
        self.assertFalse(update_check_due(100, now=100 + day - 1))
        self.assertTrue(update_check_due(100, now=100 + day))

    def test_new_settings_fields_round_trip(self) -> None:
        settings = AppSettings.from_dict(
            {"run_as_admin": True, "last_update_check": 1_700_000_000.5}
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertTrue(restored.run_as_admin)
        self.assertEqual(restored.last_update_check, 1_700_000_000.5)

    def test_release_urls_are_limited_to_official_repository(self) -> None:
        self.assertTrue(
            _is_github_url(
                "https://github.com/Scworch/KeyDeck/releases/download/v1.2.0/app.exe",
                "/Scworch/KeyDeck/releases/download/",
            )
        )
        self.assertFalse(
            _is_github_url(
                "https://example.com/KeyDeck.exe",
                "/Scworch/KeyDeck/releases/download/",
            )
        )

    def test_release_download_checks_sha256(self) -> None:
        executable = b"MZ test release"
        release = Release(
            version="1.2.0",
            tag="v1.2.0",
            page_url="https://github.com/Scworch/KeyDeck/releases/tag/v1.2.0",
            executable_url=(
                "https://github.com/Scworch/KeyDeck/releases/download/"
                "v1.2.0/KeyDeck-v1.2.0.exe"
            ),
            checksum_url=(
                "https://github.com/Scworch/KeyDeck/releases/download/"
                "v1.2.0/SHA256SUMS.txt"
            ),
        )
        checksum = f"{hashlib.sha256(executable).hexdigest()}  {release.executable_name}\n"
        responses = [io.BytesIO(checksum.encode()), io.BytesIO(executable)]

        with patch("keydeck.updates._open_url", side_effect=responses):
            executable_path, download_dir = download_release(release)
        try:
            self.assertEqual(executable_path.read_bytes(), executable)
        finally:
            shutil.rmtree(download_dir)

    def test_bad_release_checksum_is_rejected(self) -> None:
        executable = b"MZ test release"
        release = Release(
            version="1.2.0",
            tag="v1.2.0",
            page_url="https://github.com/Scworch/KeyDeck/releases/tag/v1.2.0",
            executable_url=(
                "https://github.com/Scworch/KeyDeck/releases/download/"
                "v1.2.0/KeyDeck-v1.2.0.exe"
            ),
            checksum_url=(
                "https://github.com/Scworch/KeyDeck/releases/download/"
                "v1.2.0/SHA256SUMS.txt"
            ),
        )
        temporary = Path(tempfile.mkdtemp(prefix="KeyDeck-test-"))
        responses = [io.BytesIO(b"0" * 64 + b"  KeyDeck-v1.2.0.exe\n"), io.BytesIO(executable)]
        try:
            with patch("keydeck.updates.tempfile.mkdtemp", return_value=str(temporary)), patch(
                "keydeck.updates._open_url",
                side_effect=responses,
            ):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    download_release(release)
            self.assertFalse(temporary.exists())
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def test_update_replaces_only_the_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "KeyDeck.exe"
            staged = root / "KeyDeck-new.exe"
            settings = root / "config" / "settings.json"
            current.write_bytes(b"MZ-old")
            staged.write_bytes(b"MZ-new")
            settings.parent.mkdir()
            settings.write_text('{"keep": true}', encoding="utf-8")

            with patch("keydeck.updates.wait_for_process_exit"), patch(
                "keydeck.updates.notify_shell_icon_changed"
            ) as notify_icon, patch(
                "keydeck.updates.subprocess.Popen"
            ):
                apply_update(staged, current, 1234)

            self.assertEqual(current.read_bytes(), b"MZ-new")
            self.assertEqual(settings.read_text(encoding="utf-8"), '{"keep": true}')
            self.assertFalse(current.with_name(".KeyDeck.exe.backup-1234").exists())
            notify_icon.assert_called_once_with(current.resolve())
            self.assertEqual(current.name, "KeyDeck.exe")

    def test_slot_image_options_are_normalized_and_preserved(self) -> None:
        settings = AppSettings.from_dict(
            {
                "pages": [
                    {
                        "rows": 1,
                        "columns": 1,
                        "slot_overrides": {
                            "0": {
                                "image_mode": "fit",
                                "image_zoom": 4.5,
                                "image_offset_x": -700,
                                "image_offset_y": 12,
                            }
                        },
                    }
                ]
            }
        )
        self.assertEqual(
            settings.pages[0].slot_overrides["0"],
            {
                "image_mode": "fit",
                "image_zoom": 3.0,
                "image_offset_x": -500,
                "image_offset_y": 12,
            },
        )

    def test_update_rolls_back_if_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "KeyDeck.exe"
            staged = root / "KeyDeck-new.exe"
            current.write_bytes(b"MZ-old")
            staged.write_bytes(b"MZ-new")

            with patch("keydeck.updates.wait_for_process_exit"), patch(
                "keydeck.updates.subprocess.Popen",
                side_effect=[OSError("cannot start"), None],
            ):
                with self.assertRaises(OSError):
                    apply_update(staged, current, 5678)

            self.assertEqual(current.read_bytes(), b"MZ-old")
            self.assertFalse(current.with_name(".KeyDeck.exe.backup-5678").exists())


if __name__ == "__main__":
    unittest.main()
