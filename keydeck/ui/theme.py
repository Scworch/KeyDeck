from __future__ import annotations

from PySide6.QtWidgets import QApplication


DARK_THEME = """
QWidget {
    color: #f4f4f5;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}
QDialog, QMainWindow {
    background-color: #121214;
}
QFrame#Card, QFrame#Chassis, QListWidget#Sidebar {
    background-color: #18181b;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QListWidget {
    background-color: #18181b;
    color: #f4f4f5;
    border: 1px solid #3f3f46;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #2563eb;
}
QComboBox QAbstractItemView {
    background-color: #18181b;
    color: #f4f4f5;
    selection-background-color: #2563eb;
    border: 1px solid #3f3f46;
}
QPushButton, QToolButton {
    background-color: #27272a;
    color: #f4f4f5;
    border: 1px solid #3f3f46;
    border-radius: 6px;
    padding: 5px 10px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #3f3f46;
}
QCheckBox {
    spacing: 8px;
}
QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {
    background-color: transparent;
    border: none;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    app.setStyleSheet(DARK_THEME)
