from __future__ import annotations

import gc
import json
import sys
import tempfile
import unittest
import weakref
from pathlib import Path

from keydeck.plugin_manager import PluginInfo, PluginManager


class PluginManagerTests(unittest.TestCase):
    def test_installed_plugins_are_discovered_and_loaded_after_source_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source_plugins"
            installed_dir = root / "installed_plugins"
            plugin_dir = installed_dir / "installed_sample"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "installed_sample",
                        "name": "Installed sample",
                    }
                ),
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                """
from keydeck.plugin_api import Action, PluginBase

class Plugin(PluginBase):
    def actions(self):
        return [Action("installed_sample.run", "Run", lambda: None)]
""",
                encoding="utf-8",
            )
            manager = PluginManager(
                source_dir,
                data_dir=root / "plugin_data",
                additional_plugins_dirs=(installed_dir,),
            )

            self.assertEqual(
                manager.discover_plugins(),
                [PluginInfo("installed_sample", "Installed sample")],
            )

            manager.load_plugins()
            self.assertEqual(
                [action.action_id for action in manager.all_actions()],
                ["installed_sample.run"],
            )
            self.assertTrue(
                (root / "plugin_data" / "installed_sample" / "settings.json").is_file()
            )
            manager.unload_plugins()

    def test_source_plugin_takes_precedence_over_duplicate_installed_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source_plugins"
            installed_dir = root / "installed_plugins"
            for plugins_dir, title in (
                (source_dir, "Source"),
                (installed_dir, "Installed"),
            ):
                plugin_dir = plugins_dir / "sample"
                plugin_dir.mkdir(parents=True)
                (plugin_dir / "manifest.json").write_text(
                    json.dumps({"id": "same_id", "name": title}),
                    encoding="utf-8",
                )
                (plugin_dir / "plugin.py").write_text(
                    f"""
from keydeck.plugin_api import Action, PluginBase

class Plugin(PluginBase):
    def actions(self):
        return [Action("same_id.run", {title!r}, lambda: None)]
""",
                    encoding="utf-8",
                )
            manager = PluginManager(
                source_dir,
                data_dir=root / "plugin_data",
                additional_plugins_dirs=(installed_dir,),
            )

            self.assertEqual(
                manager.discover_plugins(),
                [PluginInfo("same_id", "Source")],
            )
            manager.load_plugins()
            self.assertEqual(manager.all_actions()[0].title, "Source")
            manager.unload_plugins()

    def test_retired_plugin_is_not_discovered_or_imported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_dir = root / "plugins" / "ShortcutLauncher"
            plugin_dir.mkdir(parents=True)
            imported = root / "imported"
            (plugin_dir / "manifest.json").write_text(
                json.dumps(
                    {"id": "ShortcutLauncher", "name": "Shortcut Launcher"}
                ),
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                f"from pathlib import Path\nPath({str(imported)!r}).touch()\n",
                encoding="utf-8",
            )
            manager = PluginManager(
                root / "plugins",
                data_dir=root / "data",
                retired_plugin_ids={"ShortcutLauncher"},
            )

            self.assertEqual(manager.discover_plugins(), [])
            manager.load_plugins()

            self.assertEqual(manager.all_actions(), [])
            self.assertFalse(imported.exists())
            manager.unload_plugins()

    def test_action_can_disable_generic_json_settings_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_dir = Path(temp_dir) / "plugins" / "button_only"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "manifest.json").write_text(
                json.dumps({"id": "button_only", "name": "Button only"}),
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                """
from keydeck.plugin_api import Action, PluginBase

class Plugin(PluginBase):
    def actions(self):
        return [Action(
            action_id="button_only.run",
            title="Run",
            callback=lambda: None,
            plugin_id="button_only",
            plugin_settings_enabled=False,
        )]
""",
                encoding="utf-8",
            )
            manager = PluginManager(plugin_dir.parent, data_dir=Path(temp_dir) / "data")
            manager.load_plugins()

            action = manager.all_actions()[0]

            self.assertIsNone(action.settings_callback)
            manager.unload_plugins()

    def test_plugin_context_exposes_action_refresh_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_dir = root / "plugins" / "refresh_sample"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "manifest.json").write_text(
                json.dumps({"id": "refresh_sample"}),
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                """
from keydeck.plugin_api import Action, PluginBase

class Plugin(PluginBase):
    def actions(self):
        return [Action("refresh_sample.run", "Run", lambda: None)]
""",
                encoding="utf-8",
            )
            refreshes: list[bool] = []
            manager = PluginManager(
                root / "plugins",
                data_dir=root / "data",
                refresh_actions=lambda: refreshes.append(True),
            )
            manager.load_plugins()

            manager.plugins[0].context.refresh_actions()

            self.assertEqual(refreshes, [True])
            manager.unload_plugins()

    def test_disabled_plugin_is_not_imported_and_releases_loaded_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_id = "lifecycle_test"
            plugin_dir = root / "plugins" / plugin_id
            plugin_dir.mkdir(parents=True)
            import_marker = root / "imported"
            stop_marker = root / "stopped"
            (plugin_dir / "manifest.json").write_text(
                json.dumps({"id": plugin_id, "name": "Lifecycle test"}),
                encoding="utf-8",
            )
            (plugin_dir / "lifecycle_test_helper.py").write_text(
                "VALUE = 'loaded'\n",
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                f"""
from pathlib import Path
import sys
from keydeck.plugin_api import Action, PluginBase

Path({str(import_marker)!r}).write_text("yes", encoding="utf-8")
plugin_dir = str(Path(__file__).parent)
sys.path.insert(0, plugin_dir)
import lifecycle_test_helper

class Plugin(PluginBase):
    plugin_name = "Lifecycle test"

    def actions(self):
        return [Action(
            action_id={f"{plugin_id}.run"!r},
            title="Run",
            callback=self.run,
            plugin_id={plugin_id!r},
        )]

    def run(self):
        pass

    def stop(self):
        Path({str(stop_marker)!r}).write_text("yes", encoding="utf-8")
""",
                encoding="utf-8",
            )
            invoked: list[tuple[str, int]] = []
            manager = PluginManager(
                root / "plugins",
                data_dir=root / "data",
                get_assigned_slots=lambda: [{"action_id": f"{plugin_id}.run"}],
                invoke_assigned_slot=lambda page_id, slot: invoked.append((page_id, slot)),
            )

            self.assertEqual(
                manager.discover_plugins(),
                [PluginInfo(plugin_id, "Lifecycle test")],
            )
            manager.load_plugins({plugin_id})
            manager.start_plugins()
            self.assertFalse(import_marker.exists())
            self.assertEqual(manager.all_actions(), [])
            self.assertEqual(manager.get_plugins(), [])

            manager.load_plugins()
            manager.start_plugins()
            self.assertTrue(import_marker.exists())
            self.assertIn(f"keydeck_plugin_{plugin_id}", sys.modules)
            self.assertIn("lifecycle_test_helper", sys.modules)
            self.assertIn(str(plugin_dir), sys.path)
            self.assertEqual(
                manager.plugins[0].context.assigned_plugin_slots(),
                [{"action_id": f"{plugin_id}.run"}],
            )
            manager.plugins[0].context.invoke_plugin_slot("main", 2)
            self.assertEqual(invoked, [("main", 2)])
            self.assertEqual(
                [action.action_id for action in manager.all_actions()],
                [f"{plugin_id}.run"],
            )
            plugin_reference = weakref.ref(manager.plugins[0])

            manager.load_plugins({plugin_id})
            gc.collect()

            self.assertTrue(stop_marker.exists())
            self.assertNotIn(f"keydeck_plugin_{plugin_id}", sys.modules)
            self.assertNotIn("lifecycle_test_helper", sys.modules)
            self.assertNotIn(str(plugin_dir), sys.path)
            self.assertIsNone(plugin_reference())
            self.assertEqual(manager.all_actions(), [])
            self.assertEqual(manager.get_plugins(), [])


if __name__ == "__main__":
    unittest.main()
