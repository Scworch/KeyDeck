from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keydeck.config import AppSettings
from keydeck.plugin_api import Action


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        actions: list[Action],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CFG")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(460)

        self.actions = actions
        self._action_by_id = {action.action_id: action for action in actions}
        self._slot_actions = list(settings.slot_actions)

        layout = QVBoxLayout(self)

        top_form = QFormLayout()
        layout.addLayout(top_form)

        self.rows_spin = QSpinBox(self)
        self.rows_spin.setRange(1, 8)
        self.rows_spin.setValue(settings.rows)
        top_form.addRow("Rows", self.rows_spin)

        self.columns_spin = QSpinBox(self)
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setValue(settings.columns)
        top_form.addRow("Columns", self.columns_spin)

        self.size_combo = QComboBox(self)
        self.size_combo.addItem("Small", "small")
        self.size_combo.addItem("Medium", "medium")
        self.size_combo.addItem("Large", "large")
        self._set_combo_data(self.size_combo, settings.button_size)
        top_form.addRow("Button size", self.size_combo)

        self.grid_editor = QWidget(self)
        self.grid_editor_layout = QVBoxLayout(self.grid_editor)
        self.grid_editor_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_editor_layout.setSpacing(6)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_editor)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.rows_spin.valueChanged.connect(self._rebuild_grid_editor)
        self.columns_spin.valueChanged.connect(self._rebuild_grid_editor)
        self._rebuild_grid_editor()

    def to_settings(self) -> AppSettings:
        settings = AppSettings(
            rows=self.rows_spin.value(),
            columns=self.columns_spin.value(),
            button_size=str(self.size_combo.currentData() or "medium"),
            slot_actions=self._slot_actions,
        )
        return settings.clamp()

    def _rebuild_grid_editor(self) -> None:
        while self.grid_editor_layout.count():
            item = self.grid_editor_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        total = self.rows_spin.value() * self.columns_spin.value()
        if len(self._slot_actions) < total:
            self._slot_actions.extend([None] * (total - len(self._slot_actions)))
        self._slot_actions = self._slot_actions[:total]

        for slot in range(total):
            row = slot // self.columns_spin.value() + 1
            col = slot % self.columns_spin.value() + 1
            row_widget = QWidget(self.grid_editor)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            title = QLabel(f"Slot {slot + 1} (R{row}:C{col})", row_widget)
            title.setMinimumWidth(120)
            row_layout.addWidget(title)

            combo = QComboBox(row_widget)
            combo.addItem("<Empty>", "")
            for action in self.actions:
                combo.addItem(f"{action.title} [{action.plugin_id}]", action.action_id)
            self._set_combo_data(combo, self._slot_actions[slot] or "")
            combo.currentIndexChanged.connect(
                lambda _idx, s=slot, cb=combo: self._on_slot_changed(s, cb)
            )
            row_layout.addWidget(combo, 1)

            plugin_button = QPushButton("Plugin settings", row_widget)
            plugin_button.clicked.connect(lambda _checked=False, s=slot: self._open_plugin_settings(s))
            row_layout.addWidget(plugin_button)

            self.grid_editor_layout.addWidget(row_widget)

        self.grid_editor_layout.addStretch(1)

    def _on_slot_changed(self, slot: int, combo: QComboBox) -> None:
        data = combo.currentData()
        self._slot_actions[slot] = str(data) if data else None

    def _open_plugin_settings(self, slot: int) -> None:
        action_id = self._slot_actions[slot]
        if not action_id:
            QMessageBox.information(self, "Plugin settings", "Select action for this slot first.")
            return

        action = self._action_by_id.get(action_id)
        if action is None:
            QMessageBox.warning(self, "Plugin settings", f"Action not found: {action_id}")
            return

        if action.settings_callback is None:
            QMessageBox.information(
                self,
                "Plugin settings",
                f"Action '{action.title}' has no plugin settings.",
            )
            return

        try:
            action.settings_callback()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Plugin settings", str(exc))

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)
