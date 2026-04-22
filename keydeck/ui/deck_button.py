from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class DeckButtonWidget(QWidget):
    clicked = Signal(int)

    def __init__(self, index: int, title: str, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._index = index

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.button = QPushButton("", self)
        self.button.setFixedSize(size, size)
        self.button.clicked.connect(self._emit_click)
        self.button.setCursor(Qt.PointingHandCursor)
        self._apply_squircle_style(size)

        self.label = QLabel(title, self)
        self.label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #e6e6e6; font-size: 11px;")
        self.label.setFixedWidth(size)

        layout.addWidget(self.button, alignment=Qt.AlignHCenter)
        layout.addWidget(self.label, alignment=Qt.AlignHCenter)

    def set_title(self, title: str) -> None:
        self.label.setText(title)

    def _emit_click(self) -> None:
        self.clicked.emit(self._index)

    def _apply_squircle_style(self, size: int) -> None:
        radius = max(14, int(size * 0.28))
        self.button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: {radius}px;
            }}
            QPushButton:hover {{
                background-color: #3a3a3a;
            }}
            QPushButton:pressed {{
                background-color: #1f1f1f;
            }}
            """
        )
