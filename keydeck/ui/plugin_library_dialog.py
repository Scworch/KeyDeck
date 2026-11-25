from __future__ import annotations

import zipfile
from collections.abc import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from keydeck.plugin_store import PluginCatalogEntry, PluginStore, version_key
from keydeck.ui.theme import size_dialog


_PERMISSION_LABELS = {
    "filesystem": "Read or change files",
    "network": "Use network connections",
    "plugin_control": "Invoke actions assigned to other KeyDeck buttons",
    "process": "Start or control processes",
    "system_audio": "Read or change system audio",
    "system_input": "Read keyboard and input events",
    "system_network": "Read or change network configuration",
    "system_settings": "Change system or display settings",
}


class PluginLibraryWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        store: PluginStore,
        operation: str,
        entry: PluginCatalogEntry | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.operation = operation
        self.entry = entry

    def run(self) -> None:
        try:
            if self.operation == "refresh":
                result = self.store.fetch_catalog()
            elif self.operation == "install" and self.entry is not None:
                result = self.store.install(self.entry, consent=True)
            elif self.operation == "uninstall" and self.entry is not None:
                self.store.uninstall(self.entry.plugin_id)
                result = None
            elif self.operation == "rollback" and self.entry is not None:
                result = self.store.rollback(self.entry.plugin_id)
            else:
                raise ValueError("Invalid plugin library operation")
        except (
            EOFError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            zipfile.BadZipFile,
        ) as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class PluginLibraryDialog(QDialog):
    def __init__(
        self,
        store: PluginStore,
        source_plugin_ids: set[str],
        before_mutation: Callable[[], None],
        after_mutation: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.source_plugin_ids = source_plugin_ids
        self.before_mutation = before_mutation
        self.after_mutation = after_mutation
        self.entries: list[PluginCatalogEntry] = []
        self._entry_by_id: dict[str, PluginCatalogEntry] = {}
        self._worker: PluginLibraryWorker | None = None
        self._operation = ""

        self.setWindowTitle("KeyDeck Plugin Library")
        self.setModal(True)
        size_dialog(self, 920, 680, 760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        heading = QLabel("Plugin Library", self)
        heading.setObjectName("PageTitle")
        root.addWidget(heading)
        intro = QLabel(
            "Plugins are versioned and installed separately from KeyDeck. "
            "Their settings and cache are kept when plugin code is removed.",
            self,
        )
        intro.setObjectName("PageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search plugins")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_entries)
        root.addWidget(self.search_edit)

        content = QHBoxLayout()
        content.setSpacing(14)
        self.plugin_list = QListWidget(self)
        self.plugin_list.currentRowChanged.connect(self._show_selected)
        content.addWidget(self.plugin_list, 1)

        detail_card = QFrame(self)
        detail_card.setObjectName("Card")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(18, 18, 18, 16)
        detail_layout.setSpacing(9)
        self.name_label = QLabel("Select a plugin", detail_card)
        self.name_label.setObjectName("SectionTitle")
        self.version_label = QLabel("", detail_card)
        self.version_label.setObjectName("Muted")
        self.description_label = QLabel(
            "Choose a catalog entry to see its details.", detail_card
        )
        self.description_label.setWordWrap(True)
        self.permissions_label = QLabel("", detail_card)
        self.permissions_label.setWordWrap(True)
        self.permissions_label.setObjectName("Muted")
        self.access_warning_label = QLabel(
            "Python plugins are not sandboxed and run with your Windows account's "
            "permissions. Declared capabilities are informational, not an OS-level "
            "restriction.",
            detail_card,
        )
        self.access_warning_label.setWordWrap(True)
        self.access_warning_label.setObjectName("Muted")
        self.status_label = QLabel("", detail_card)
        self.status_label.setWordWrap(True)
        detail_layout.addWidget(self.name_label)
        detail_layout.addWidget(self.version_label)
        detail_layout.addWidget(self.description_label)
        detail_layout.addWidget(self.permissions_label)
        detail_layout.addWidget(self.access_warning_label)
        detail_layout.addWidget(self.status_label)
        detail_layout.addStretch(1)

        actions = QHBoxLayout()
        self.install_button = QPushButton("Install", detail_card)
        self.install_button.setObjectName("PrimaryButton")
        self.install_button.clicked.connect(self._install_selected)
        self.remove_button = QPushButton("Remove", detail_card)
        self.remove_button.setObjectName("QuietButton")
        self.remove_button.clicked.connect(self._remove_selected)
        self.rollback_button = QPushButton("Roll back", detail_card)
        self.rollback_button.setObjectName("QuietButton")
        self.rollback_button.clicked.connect(self._rollback_selected)
        actions.addWidget(self.install_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.rollback_button)
        detail_layout.addLayout(actions)
        content.addWidget(detail_card, 2)
        root.addLayout(content, 1)

        bottom = QHBoxLayout()
        self.catalog_status_label = QLabel("", self)
        self.catalog_status_label.setObjectName("Muted")
        bottom.addWidget(self.catalog_status_label, 1)
        self.refresh_button = QPushButton("Refresh catalog", self)
        self.refresh_button.setObjectName("QuietButton")
        self.refresh_button.clicked.connect(self._refresh_catalog)
        bottom.addWidget(self.refresh_button)
        close_button = QPushButton("Close", self)
        close_button.setObjectName("QuietButton")
        close_button.clicked.connect(self.accept)
        bottom.addWidget(close_button)
        root.addLayout(bottom)

        try:
            self._set_entries(store.bundled_catalog())
            self.catalog_status_label.setText("Showing the bundled catalog.")
        except (OSError, ValueError) as exc:
            self.catalog_status_label.setText(str(exc))
        self._refresh_catalog()

    def _set_entries(self, entries: list[PluginCatalogEntry]) -> None:
        selected_id = (
            self.plugin_list.currentItem().data(Qt.ItemDataRole.UserRole)
            if self.plugin_list.currentItem()
            else None
        )
        self.entries = entries
        self._entry_by_id = {entry.plugin_id: entry for entry in entries}
        self.plugin_list.clear()
        selected_row = 0
        for index, entry in enumerate(entries):
            item = QListWidgetItem(entry.name)
            item.setData(Qt.ItemDataRole.UserRole, entry.plugin_id)
            item.setToolTip(f"{entry.plugin_id} · v{entry.version}")
            self.plugin_list.addItem(item)
            if entry.plugin_id == selected_id:
                selected_row = index
        self.plugin_list.setCurrentRow(selected_row if entries else -1)
        self._filter_entries(self.search_edit.text())
        self._show_selected(self.plugin_list.currentRow())

    def _filter_entries(self, text: str) -> None:
        query = text.casefold().strip()
        for row in range(self.plugin_list.count()):
            item = self.plugin_list.item(row)
            plugin_id = item.data(Qt.ItemDataRole.UserRole)
            entry = self._entry_by_id[plugin_id]
            searchable = f"{entry.name} {entry.plugin_id} {entry.description}".casefold()
            item.setHidden(bool(query) and query not in searchable)
        if self.plugin_list.currentItem() and self.plugin_list.currentItem().isHidden():
            for row in range(self.plugin_list.count()):
                if not self.plugin_list.item(row).isHidden():
                    self.plugin_list.setCurrentRow(row)
                    return

    def _show_selected(self, row: int) -> None:
        if not 0 <= row < self.plugin_list.count():
            self.name_label.setText("No plugin selected")
            self.version_label.clear()
            self.description_label.clear()
            self.permissions_label.clear()
            self.status_label.clear()
            self._set_action_buttons(False, False, False)
            return
        item = self.plugin_list.item(row)
        entry = self._entry_by_id[item.data(Qt.ItemDataRole.UserRole)]
        self.name_label.setText(entry.name)
        self.version_label.setText(
            f"{entry.plugin_id} · catalog version {entry.version} "
            f"(KeyDeck {entry.min_keydeck_version}+"
            + (
                f", up to {entry.max_keydeck_version}"
                if entry.max_keydeck_version is not None
                else ""
            )
            + ")"
        )
        self.description_label.setText(entry.description)
        permission_names = [
            _PERMISSION_LABELS[permission] for permission in entry.permissions
        ]
        self.permissions_label.setText(
            "Declared capabilities: "
            + (", ".join(permission_names) if permission_names else "none")
        )

        try:
            installed_version = self.store.installed_version(entry.plugin_id)
            install_error = ""
        except (OSError, ValueError) as exc:
            installed_version = None
            install_error = str(exc)
        from_source = (
            entry.plugin_id in self.source_plugin_ids
            and installed_version is None
        )
        incompatible = version_key(entry.min_keydeck_version) > version_key(
            self.store.keydeck_version
        )
        incompatible = incompatible or (
            entry.max_keydeck_version is not None
            and version_key(self.store.keydeck_version)
            > version_key(entry.max_keydeck_version)
        )
        if incompatible:
            status = (
                f"Plugin supports KeyDeck {entry.min_keydeck_version}+"
                + (
                    f" through {entry.max_keydeck_version}"
                    if entry.max_keydeck_version is not None
                    else ""
                )
                + f"; this version is {self.store.keydeck_version}."
            )
        elif install_error:
            status = f"Installed plugin is damaged: {install_error}"
        elif from_source:
            status = "Provided by the current source checkout."
        elif installed_version is None:
            status = "Not installed."
        elif version_key(installed_version) == version_key(entry.version):
            status = f"Installed · v{installed_version} (up to date)"
        elif version_key(installed_version) < version_key(entry.version):
            status = f"Installed · v{installed_version}; v{entry.version} is available."
        else:
            status = f"Installed · v{installed_version} (newer than this catalog)"
        if self.store.has_rollback(entry.plugin_id):
            status += " A previous version is available for rollback."
        self.status_label.setText(status)

        can_install = (
            not from_source
            and not incompatible
            and not install_error
            and (
                installed_version is None
                or version_key(installed_version) < version_key(entry.version)
            )
        )
        self.install_button.setText(
            "Update" if installed_version is not None else "Install"
        )
        self._set_action_buttons(
            can_install,
            self.store.is_installed(entry.plugin_id) and not from_source,
            installed_version is not None
            and not install_error
            and self.store.has_rollback(entry.plugin_id),
        )

    def _set_action_buttons(
        self,
        can_install: bool,
        can_remove: bool,
        can_rollback: bool,
    ) -> None:
        active = self._worker is None
        self.install_button.setEnabled(active and can_install)
        self.remove_button.setEnabled(active and can_remove)
        self.rollback_button.setEnabled(active and can_rollback)

    def _refresh_catalog(self) -> None:
        self._start_operation("refresh")

    def _install_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        details = "\n".join(
            f"- {_PERMISSION_LABELS[permission]}"
            for permission in entry.permissions
        )
        if not details:
            details = "- No capabilities declared"
        answer = QMessageBox.warning(
            self,
            f"Install {entry.name}?",
            f"This will install {entry.name} v{entry.version} from the official "
            "KeyDeck GitHub release.\n\n"
            f"Declared capabilities:\n{details}\n\n"
            "The plugin is Python code, is not sandboxed, and can use all "
            "permissions of your Windows account. The declared list does not "
            "technically restrict it. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_operation("install", entry)

    def _remove_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        answer = QMessageBox.question(
            self,
            f"Remove {entry.name}?",
            "Remove plugin code? Its settings, cache, and button assignments will "
            "be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_operation("uninstall", entry)

    def _rollback_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        answer = QMessageBox.question(
            self,
            f"Roll back {entry.name}?",
            "Restore the previous plugin version?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_operation("rollback", entry)

    def _selected_entry(self) -> PluginCatalogEntry | None:
        item = self.plugin_list.currentItem()
        if item is None:
            return None
        return self._entry_by_id.get(item.data(Qt.ItemDataRole.UserRole))

    def _start_operation(
        self,
        operation: str,
        entry: PluginCatalogEntry | None = None,
    ) -> None:
        if self._worker is not None:
            return
        if operation != "refresh":
            try:
                self.before_mutation()
            except (OSError, RuntimeError, ValueError) as exc:
                self.after_mutation()
                QMessageBox.critical(self, "Plugin Library", str(exc))
                return
        self._operation = operation
        self._set_action_buttons(False, False, False)
        self.refresh_button.setEnabled(False)
        if operation == "refresh":
            message = "Refreshing catalog..."
        elif operation == "install" and entry is not None:
            message = f"Downloading and verifying {entry.name}..."
        elif operation == "uninstall" and entry is not None:
            message = f"Removing {entry.name}..."
        elif operation == "rollback" and entry is not None:
            message = f"Restoring previous {entry.name} version..."
        else:
            raise ValueError(f"Unknown plugin library operation: {operation}")
        self.catalog_status_label.setText(message)
        self._worker = PluginLibraryWorker(self.store, operation, entry)
        self._worker.succeeded.connect(self._operation_succeeded)
        self._worker.failed.connect(self._operation_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.catalog_status_label.setText(
                "Please wait for the current plugin operation to finish."
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _operation_succeeded(self, result: object) -> None:
        operation = self._operation
        entry = self._worker.entry if self._worker is not None else None
        self._worker = None
        if operation == "refresh":
            self._set_entries(result if isinstance(result, list) else [])
            self.catalog_status_label.setText("Catalog refreshed.")
        else:
            self.after_mutation()
            self.catalog_status_label.setText(
                f"{entry.name if entry is not None else 'Plugin'} operation completed."
            )
            if operation == "uninstall":
                QMessageBox.information(
                    self,
                    "Plugin removed",
                    "Plugin code was removed. Its settings and cache were kept.",
                )
        self.refresh_button.setEnabled(True)
        self._show_selected(self.plugin_list.currentRow())

    def _operation_failed(self, message: str) -> None:
        operation = self._operation
        entry = self._worker.entry if self._worker is not None else None
        self._worker = None
        if operation != "refresh":
            self.after_mutation()
        self.refresh_button.setEnabled(True)
        if operation == "refresh":
            self.catalog_status_label.setText(
                f"Catalog refresh failed: {message}. Showing the bundled catalog."
            )
        else:
            self.catalog_status_label.setText(
                f"{entry.name if entry is not None else 'Plugin'} operation failed."
            )
        self._show_selected(self.plugin_list.currentRow())
        if operation != "refresh":
            QMessageBox.critical(self, "Plugin Library", message)
