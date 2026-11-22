from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QDialog


DARK_THEME = """
QWidget {
    color: #f3f3f3;
    font-family: "@FONT_FAMILY@";
    font-size: 13px;
}
QDialog, QMainWindow {
    background-color: #262626;
}
QFrame#NavigationPanel {
    background-color: #1b1b1b;
}
QLabel#PageTitle {
    color: #f3f3f3;
    font-size: 25px;
    font-weight: 600;
}
QLabel#PageSubtitle {
    color: #c5c5c5;
}
QLabel#Muted, QLabel#SectionEyebrow {
    color: #a0a0a0;
}
QLabel#SectionEyebrow {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#SectionTitle {
    color: #f3f3f3;
    font-size: 16px;
    font-weight: 600;
}
QLabel#VersionValue {
    color: #f3f3f3;
    font-size: 24px;
    font-weight: 600;
}
QFrame#Card, QFrame#Panel {
    background-color: #303030;
    border: none;
    border-radius: 2px;
}
QFrame#PreviewSurface {
    background-color: #292929;
    border: none;
    border-radius: 2px;
}
QFrame#Chassis {
    background-color: #242424;
    border: none;
    border-radius: 2px;
}
QFrame#ErrorCard {
    background-color: #3a2525;
    border: none;
    border-radius: 2px;
}
QLabel#ErrorTitle {
    color: #ffb4ab;
    font-weight: 600;
}
QLabel#WarningText {
    color: #f7c77b;
}
QLabel#StatusBadge {
    background-color: #234039;
    color: #a8d7c3;
    border: none;
    border-radius: 4px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 600;
}
QListWidget, QTreeWidget, QTableWidget {
    background-color: #202020;
    color: #f3f3f3;
    border: 1px solid #3a3a3a;
    border-radius: 2px;
    outline: none;
    padding: 4px;
    selection-background-color: #333333;
    selection-color: #ffffff;
}
QListWidget::item, QTreeWidget::item {
    border-radius: 2px;
    min-height: 22px;
    margin: 3px 2px;
    padding: 6px 9px;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: #333333;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: #383838;
    color: #ffffff;
}
QListWidget#Sidebar {
    background-color: #191919;
    border: none;
    padding: 0;
    border-radius: 0;
}
QListWidget#Sidebar::item {
    min-height: 24px;
    margin: 3px 0;
    padding: 8px 12px;
    border-radius: 0;
}
QListWidget#Sidebar::item:hover {
    background-color: #292929;
}
QListWidget#Sidebar::item:selected {
    background-color: #303030;
    border-left: 3px solid @ACCENT@;
    padding-left: 9px;
}
QListWidget#ErrorList {
    background-color: #2b2424;
    border: 1px solid #473131;
    border-radius: 2px;
    padding: 0;
}
QListWidget#ErrorList::item {
    color: #ffc9c6;
    margin: 2px 4px;
    padding: 4px 6px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background-color: #222222;
    color: #f3f3f3;
    border: 1px solid #4a4a4a;
    border-radius: 2px;
    padding: 6px 8px;
    min-height: 22px;
    selection-background-color: #005fb8;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid @ACCENT@;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QLineEdit[readOnly="true"] {
    background-color: #262626;
    color: #8a8a8a;
    border-color: #303030;
}
QComboBox QAbstractItemView {
    background-color: #303030;
    color: #f3f3f3;
    border: none;
    selection-background-color: #383838;
}
QPushButton, QToolButton {
    background-color: #343434;
    color: #f3f3f3;
    border: 1px solid #444444;
    border-radius: 2px;
    padding: 7px 12px;
    min-height: 20px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #414141;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: #292929;
}
QPushButton:disabled, QToolButton:disabled {
    background-color: #2a2a2a;
    color: #777777;
}
QPushButton:focus, QToolButton:focus {
    border-color: @ACCENT@;
}
QPushButton#PrimaryButton {
    background-color: @ACCENT@;
    color: #ffffff;
    border: 1px solid @ACCENT@;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: @ACCENT_HOVER@;
}
QPushButton#PrimaryButton:disabled {
    background-color: #363636;
    color: #8a8a8a;
}
QPushButton#DangerButton {
    background-color: #3a2828;
    color: #ffb4ab;
    border-color: #553737;
}
QPushButton#DangerButton:hover {
    background-color: #493030;
}
QPushButton#QuietButton, QToolButton#QuietButton {
    background-color: #343434;
    border: 1px solid #444444;
}
QPushButton#QuietButton:hover, QToolButton#QuietButton:hover {
    background-color: #414141;
}
QPushButton#PrimaryButton:focus, QPushButton#QuietButton:focus,
QPushButton#DangerButton:focus, QToolButton#QuietButton:focus {
    border: 1px solid @ACCENT@;
}
QPushButton#UiButton {
    background-color: #343434;
}
QCheckBox {
    spacing: 9px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #555555;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: @ACCENT@;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 2px;
    background: #f3f3f3;
    border: 2px solid @ACCENT@;
}
QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 1px;
}
QScrollBar::handle:vertical {
    background: #555555;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #707070;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 1px 4px;
}
QScrollBar::handle:horizontal {
    background: #555555;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #707070;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
    width: 0;
}
QMenu {
    background-color: #303030;
    color: #f3f3f3;
    border: none;
    border-radius: 2px;
    padding: 4px;
}
QMenu::item {
    border-radius: 2px;
    padding: 7px 20px;
}
QMenu::item:selected {
    background-color: #383838;
}
QToolTip {
    color: #f3f3f3;
    background-color: #2b2b2b;
    border: none;
    padding: 5px 7px;
}
QDialogButtonBox QPushButton {
    min-width: 88px;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    accent_color = system_accent_color(app)
    accent = accent_color.name()
    hover = accent_color.lighter(115).name()
    families = {family.casefold(): family for family in QFontDatabase.families()}
    font_family = families.get("segoe ui variable", families.get("segoe ui", "Segoe UI"))
    app.setFont(QFont(font_family, 10))
    app.setStyleSheet(
        DARK_THEME.replace("@ACCENT@", accent)
        .replace("@ACCENT_HOVER@", hover)
        .replace("@FONT_FAMILY@", font_family)
    )


def system_accent_color(app: QApplication | None = None) -> QColor:
    application = app or QApplication.instance()
    if application is None:
        return QColor("#0078d4")
    color = application.palette().color(QPalette.ColorRole.Highlight)
    if not color.isValid() or color.lightness() < 70:
        return QColor("#0078d4")
    return color


def size_dialog(
    dialog: QDialog,
    width: int,
    height: int,
    minimum_width: int,
    minimum_height: int,
) -> None:
    application = QApplication.instance()
    if application is not None and not application.windowIcon().isNull():
        dialog.setWindowIcon(application.windowIcon())
    screen = dialog.screen() or QApplication.primaryScreen()
    if screen is None:
        dialog.setMinimumSize(minimum_width, minimum_height)
        dialog.resize(width, height)
        return

    available = screen.availableGeometry()
    max_width = max(320, available.width() - 48)
    max_height = max(320, available.height() - 48)
    minimum_width = min(minimum_width, max_width)
    minimum_height = min(minimum_height, max_height)
    dialog.setMinimumSize(minimum_width, minimum_height)
    dialog.resize(
        max(min(width, max_width), minimum_width),
        max(min(height, max_height), minimum_height),
    )
