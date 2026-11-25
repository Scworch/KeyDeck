from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from keydeck.plugin_store import (
    PluginCatalogEntry,
    PluginStore,
    parse_catalog,
)


class PluginStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = PluginStore(
            root / "installed_plugins",
            root / "backups",
            root / "catalog.json",
        )
        self.entry = self._entry()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _entry(version: str = "1.0.0") -> PluginCatalogEntry:
        return PluginCatalogEntry(
            plugin_id="SamplePlugin",
            name="Sample Plugin",
            version=version,
            description="A plugin used in tests.",
            min_keydeck_version="0.3.0",
            permissions=("filesystem",),
        )

    @staticmethod
    def _archive(
        entry: PluginCatalogEntry,
        extra_files: dict[str, bytes] | None = None,
        manifest_overrides: dict | None = None,
    ) -> bytes:
        manifest = {
            "id": entry.plugin_id,
            "name": entry.name,
            "version": entry.version,
            "min_keydeck_version": entry.min_keydeck_version,
            "permissions": list(entry.permissions),
            "action_prefixes": list(entry.action_prefixes),
            "entry": "plugin.py",
            "settings": "settings.json",
        }
        manifest.update(manifest_overrides or {})
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest),
            )
            archive.writestr(
                "plugin.py",
                "VERSION = " + repr(entry.version) + "\n",
            )
            for name, contents in (extra_files or {}).items():
                archive.writestr(name, contents)
        return output.getvalue()

    def _install_archive(
        self,
        entry: PluginCatalogEntry,
        archive: bytes,
        checksum: str | None = None,
    ) -> str:
        digest = checksum or hashlib.sha256(archive).hexdigest()
        checksum_file = (
            f"{digest}  {entry.archive_name}\n".encode("ascii")
        )
        with patch(
            "keydeck.plugin_store._open_url",
            side_effect=[io.BytesIO(checksum_file), io.BytesIO(archive)],
        ):
            return self.store.install(entry, consent=True)

    def test_bundled_catalog_contains_independently_versioned_plugins(self) -> None:
        catalog = Path(__file__).resolve().parents[1] / "plugins" / "catalog.json"

        entries = parse_catalog(catalog.read_bytes())
        data = json.loads(catalog.read_text(encoding="utf-8"))

        self.assertIn("MultiTool", {entry.plugin_id for entry in entries})
        self.assertNotIn("ShortcutLauncher", {entry.plugin_id for entry in entries})
        self.assertIn("ShortcutLauncher", data["retired_plugins"])
        self.assertTrue(all(entry.release_tag.startswith("plugin-") for entry in entries))

    def test_retired_plugin_uninstall_does_not_remove_user_data(self) -> None:
        plugin_id = "ShortcutLauncher"
        active = self.store.installed_plugins_dir / plugin_id
        backup = self.store.backup_dir / plugin_id
        user_data = Path(self.temporary.name) / "plugin_data" / plugin_id
        for folder in (active, backup, user_data):
            folder.mkdir(parents=True)
        (active / "manifest.json").write_text(
            json.dumps({"id": plugin_id, "version": "0.1.0"}),
            encoding="utf-8",
        )
        (backup / "manifest.json").write_text(
            json.dumps({"id": plugin_id, "version": "0.0.9"}),
            encoding="utf-8",
        )
        (user_data / "settings.json").write_text("{}", encoding="utf-8")

        self.store.uninstall(plugin_id)

        self.assertFalse(active.exists())
        self.assertFalse(backup.exists())
        self.assertTrue((user_data / "settings.json").is_file())

    def test_retired_plugin_cleanup_removes_backup_even_without_active_code(self) -> None:
        backup = self.store.backup_dir / "ShortcutLauncher"
        backup.mkdir(parents=True)
        (backup / "manifest.json").write_text(
            json.dumps({"id": "ShortcutLauncher", "version": "0.0.9"}),
            encoding="utf-8",
        )

        self.store.uninstall("ShortcutLauncher", allow_missing=True)

        self.assertFalse(backup.exists())

    def test_install_checks_consent_hash_and_manifest_before_activation(self) -> None:
        archive = self._archive(self.entry)
        with self.assertRaises(PermissionError):
            self.store.install(self.entry)

        version = self._install_archive(self.entry, archive)

        installed = self.store.installed_plugins_dir / self.entry.plugin_id
        self.assertEqual(version, "1.0.0")
        self.assertEqual(self.store.installed_version(self.entry.plugin_id), "1.0.0")
        self.assertTrue((installed / "plugin.py").is_file())
        self.assertEqual(
            (installed / "plugin.py").read_text(encoding="utf-8"),
            "VERSION = '1.0.0'\n",
        )

    def test_bad_checksum_does_not_install_plugin(self) -> None:
        archive = self._archive(self.entry)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._install_archive(self.entry, archive, checksum="0" * 64)

        self.assertIsNone(self.store.installed_version(self.entry.plugin_id))

    def test_archive_path_traversal_is_rejected_before_activation(self) -> None:
        archive = self._archive(
            self.entry,
            extra_files={"../outside.txt": b"not allowed"},
        )

        with self.assertRaisesRegex(ValueError, "path traversal"):
            self._install_archive(self.entry, archive)

        self.assertFalse((Path(self.temporary.name) / "outside.txt").exists())
        self.assertIsNone(self.store.installed_version(self.entry.plugin_id))

    def test_manifest_permissions_must_match_catalog(self) -> None:
        archive = self._archive(
            self.entry,
            manifest_overrides={"permissions": ["process"]},
        )

        with self.assertRaisesRegex(ValueError, "permissions"):
            self._install_archive(self.entry, archive)

        self.assertIsNone(self.store.installed_version(self.entry.plugin_id))

    def test_archive_cannot_seed_plugin_user_settings(self) -> None:
        archive = self._archive(
            self.entry,
            extra_files={"settings.json": b'{"unexpected": true}'},
        )

        with self.assertRaisesRegex(ValueError, "private or generated data"):
            self._install_archive(self.entry, archive)

        self.assertIsNone(self.store.installed_version(self.entry.plugin_id))

    def test_archive_symbolic_links_are_rejected(self) -> None:
        archive_data = io.BytesIO()
        link_info = zipfile.ZipInfo("plugin-link")
        link_info.create_system = 3
        link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive_data, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "id": self.entry.plugin_id,
                        "version": self.entry.version,
                        "min_keydeck_version": self.entry.min_keydeck_version,
                        "permissions": list(self.entry.permissions),
                        "action_prefixes": [],
                        "entry": "plugin.py",
                    }
                ),
            )
            archive.writestr("plugin.py", "pass\n")
            archive.writestr(link_info, "outside.txt")

        with self.assertRaisesRegex(ValueError, "symbolic links"):
            self._install_archive(self.entry, archive_data.getvalue())

        self.assertIsNone(self.store.installed_version(self.entry.plugin_id))

    def test_update_can_roll_back_and_uninstall_keeps_user_data(self) -> None:
        first = self._archive(self.entry)
        self._install_archive(self.entry, first)
        second_entry = self._entry("1.1.0")
        second = self._archive(second_entry)
        self._install_archive(second_entry, second)
        user_data = (
            Path(self.temporary.name)
            / "plugins"
            / self.entry.plugin_id
            / "settings.json"
        )
        user_data.parent.mkdir(parents=True)
        user_data.write_text('{"keep": true}', encoding="utf-8")

        self.assertTrue(self.store.has_rollback(self.entry.plugin_id))
        self.assertEqual(self.store.rollback(self.entry.plugin_id), "1.0.0")
        self.assertEqual(self.store.installed_version(self.entry.plugin_id), "1.0.0")

        self.store.uninstall(self.entry.plugin_id)

        self.assertIsNone(self.store.installed_version(self.entry.plugin_id))
        self.assertFalse(self.store.has_rollback(self.entry.plugin_id))
        self.assertEqual(user_data.read_text(encoding="utf-8"), '{"keep": true}')

    def test_plugin_requiring_newer_core_is_rejected(self) -> None:
        old_core_store = PluginStore(
            self.store.installed_plugins_dir,
            self.store.backup_dir,
            self.store.catalog_file,
            keydeck_version="0.2.0",
        )

        with self.assertRaisesRegex(ValueError, "newer KeyDeck"):
            old_core_store.install(self.entry, consent=True)


if __name__ == "__main__":
    unittest.main()
