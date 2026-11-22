from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from keydeck.plugin_manager import PluginManager


class PluginDataMigrationTests(unittest.TestCase):
    def test_existing_settings_and_cache_are_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "bundle" / "plugins"
            legacy = root / "install" / "plugins"
            data = root / "app-data" / "plugins"
            plugin = source / "Example"
            plugin.mkdir(parents=True)
            (plugin / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "Example",
                        "entry": "plugin.py",
                        "settings": "custom_settings.json",
                    }
                ),
                encoding="utf-8",
            )
            (plugin / "plugin.py").write_text("", encoding="utf-8")

            old_plugin = legacy / "Example"
            old_plugin.mkdir(parents=True)
            (old_plugin / "custom_settings.json").write_text(
                '{"selected": "kept"}',
                encoding="utf-8",
            )
            (old_plugin / "cache").mkdir()
            (old_plugin / "cache" / "icon.png").write_bytes(b"cache")

            manager = PluginManager(source, data_dir=data, legacy_data_dir=legacy)
            context = manager._build_context(plugin)

            self.assertEqual(
                json.loads(context.settings_file.read_text(encoding="utf-8")),
                {"selected": "kept"},
            )
            self.assertEqual(
                (context.data_dir / "cache" / "icon.png").read_bytes(),
                b"cache",
            )


if __name__ == "__main__":
    unittest.main()
