from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keydeck.config import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deck Settings")
        self.setModal(True)
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())
        layout.addLayout(form)

        self.rows_spin = QSpinBox(self)
        self.rows_spin.setRange(1, 8)
        self.rows_spin.setValue(settings.rows)
        form.addRow("Rows", self.rows_spin)

        self.columns_spin = QSpinBox(self)
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setValue(settings.columns)
        form.addRow("Columns", self.columns_spin)

        self.button_size_spin = QSpinBox(self)
        self.button_size_spin.setRange(48, 140)
        self.button_size_spin.setValue(settings.button_size)
        form.addRow("Button size", self.button_size_spin)

        self.gap_spin = QSpinBox(self)
        self.gap_spin.setRange(4, 30)
        self.gap_spin.setValue(settings.gap)
        form.addRow("Gap", self.gap_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def to_settings(self) -> AppSettings:
        return AppSettings(
            rows=self.rows_spin.value(),
            columns=self.columns_spin.value(),
            button_size=self.button_size_spin.value(),
            gap=self.gap_spin.value(),
        )
