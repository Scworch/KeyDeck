from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        reload_plugins_callback: Callable[[], list[Action]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deck Settings")
        self.setModal(True)
        self.setMinimumWidth(700)
        self.setMinimumHeight(520)
        self.setStyleSheet(
            """
            QDialog { background: #0f1115; color: #e6e6e6; }
            QLabel { color: #e6e6e6; }
            QFrame#Card { background: #151a20; border: 1px solid #27313d; border-radius: 10px; }
            QComboBox, QSpinBox {
                background: #0f141b;
                border: 1px solid #2b3847;
                border-radius: 6px;
                padding: 4px 6px;
                min-height: 24px;
            }
            QPushButton {
                background: #182230;
                border: 1px solid #2c4057;
                border-radius: 6px;
                padding: 4px 10px;
                min-height: 24px;
            }
            QPushButton:hover { background: #223347; }
            """
        )

        self.actions = actions
        self._reload_plugins_callback = reload_plugins_callback
        self._action_by_id = {action.action_id: action for action in actions}
        self._slot_actions = list(settings.slot_actions)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_top_card(settings))

        slots_card = QFrame(self)
        slots_card.setObjectName("Card")
        slots_layout = QVBoxLayout(slots_card)
        slots_layout.setContentsMargins(10, 10, 10, 10)
        slots_layout.setSpacing(8)

        title_row = QHBoxLayout()
        slots_title = QLabel("Slots", slots_card)
        slots_title.setStyleSheet("font-weight: 600;")
        title_row.addWidget(slots_title)
        title_row.addStretch(1)

        self.reload_plugins_btn = QPushButton("Reload Plugins", slots_card)
        self.reload_plugins_btn.clicked.connect(self._reload_plugins)
        title_row.addWidget(self.reload_plugins_btn)
        slots_layout.addLayout(title_row)

        self.grid_editor = QWidget(slots_card)
        self.grid_editor_layout = QVBoxLayout(self.grid_editor)
        self.grid_editor_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_editor_layout.setSpacing(6)

        scroll = QScrollArea(slots_card)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_editor)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        slots_layout.addWidget(scroll)
        root.addWidget(slots_card, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.rows_spin.valueChanged.connect(self._rebuild_grid_editor)
        self.columns_spin.valueChanged.connect(self._rebuild_grid_editor)
        self._rebuild_grid_editor()

    def _build_top_card(self, settings: AppSettings) -> QFrame:
        card = QFrame(self)
        card.setObjectName("Card")
        layout = QGridLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)

        title = QLabel("Layout", card)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title, 0, 0, 1, 6)

        self.rows_spin = QSpinBox(card)
        self.rows_spin.setRange(1, 8)
        self.rows_spin.setValue(settings.rows)
        layout.addWidget(QLabel("Rows", card), 1, 0)
        layout.addWidget(self.rows_spin, 1, 1)

        self.columns_spin = QSpinBox(card)
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setValue(settings.columns)
        layout.addWidget(QLabel("Columns", card), 1, 2)
        layout.addWidget(self.columns_spin, 1, 3)

        self.size_combo = QComboBox(card)
        self.size_combo.addItem("Small", "small")
        self.size_combo.addItem("Medium", "medium")
        self.size_combo.addItem("Large", "large")
        self._set_combo_data(self.size_combo, settings.button_size)
        layout.addWidget(QLabel("Button size", card), 1, 4)
        layout.addWidget(self.size_combo, 1, 5)

        return card

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
            row_idx = slot // self.columns_spin.value() + 1
            col_idx = slot % self.columns_spin.value() + 1
            row_widget = QFrame(self.grid_editor)
            row_widget.setObjectName("Card")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 6, 8, 6)
            row_layout.setSpacing(8)

            title = QLabel(f"#{slot + 1}  R{row_idx}C{col_idx}", row_widget)
            title.setMinimumWidth(90)
            title.setStyleSheet("color: #a9b8c8;")
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

            plugin_button = QPushButton("Plugin Settings", row_widget)
            plugin_button.clicked.connect(lambda _checked=False, s=slot: self._open_plugin_settings(s))
            row_layout.addWidget(plugin_button)

            self.grid_editor_layout.addWidget(row_widget)

        self.grid_editor_layout.addStretch(1)

    def _reload_plugins(self) -> None:
        if self._reload_plugins_callback is None:
            return
        try:
            self.actions = self._reload_plugins_callback()
            self._action_by_id = {action.action_id: action for action in self.actions}
            self._rebuild_grid_editor()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Reload Plugins", str(exc))

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
            # Auto-refresh plugin list and action titles right after settings changes.
            self._reload_plugins()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Plugin settings", str(exc))

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)
