from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from keydeck.plugin_store import PluginStore
from keydeck.ui.plugin_library_dialog import PluginLibraryDialog


class PluginLibraryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_library_search_lists_catalog_and_reports_current_install_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            store = PluginStore(
                Path(temporary) / "installed",
                Path(temporary) / "backups",
                root / "plugins" / "catalog.json",
            )
            entries = store.bundled_catalog()
            with patch.object(PluginStore, "fetch_catalog", return_value=entries):
                dialog = PluginLibraryDialog(
                    store,
                    source_plugin_ids=set(),
                    before_mutation=lambda: None,
                    after_mutation=lambda: None,
                )
                worker = dialog._worker
                try:
                    if worker is not None:
                        worker.wait(5000)
                        self.app.processEvents()

                    self.assertEqual(dialog.plugin_list.count(), len(entries))
                    dialog.search_edit.setText("wavelink")
                    visible = [
                        dialog.plugin_list.item(row).text()
                        for row in range(dialog.plugin_list.count())
                        if not dialog.plugin_list.item(row).isHidden()
                    ]
                    self.assertEqual(visible, ["Wave Link"])
                    self.assertIn("Not installed", dialog.status_label.text())
                    self.assertTrue(dialog.install_button.isEnabled())
                finally:
                    dialog.close()

    def test_catalog_refresh_failure_keeps_bundled_entries(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            store = PluginStore(
                Path(temporary) / "installed",
                Path(temporary) / "backups",
                root / "plugins" / "catalog.json",
            )
            with patch.object(
                PluginStore,
                "fetch_catalog",
                side_effect=OSError("offline"),
            ):
                dialog = PluginLibraryDialog(
                    store,
                    source_plugin_ids=set(),
                    before_mutation=lambda: None,
                    after_mutation=lambda: None,
                )
                worker = dialog._worker
                try:
                    if worker is not None:
                        worker.wait(5000)
                        self.app.processEvents()

                    self.assertEqual(dialog.plugin_list.count(), len(store.bundled_catalog()))
                    self.assertIn("bundled catalog", dialog.catalog_status_label.text())
                finally:
                    dialog.close()


if __name__ == "__main__":
    unittest.main()
