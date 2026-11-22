from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from keydeck.ui.theme import system_accent_color


def add_dialog_header(
    layout: QVBoxLayout,
    title: str,
    description: str,
    parent: QWidget,
) -> None:
    heading = QLabel(title, parent)
    heading.setObjectName("PageTitle")
    layout.addWidget(heading)

    subtitle = QLabel(description, parent)
    subtitle.setObjectName("PageSubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)


class SettingsSection(QWidget):
    def __init__(
        self,
        title: str,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        heading = QLabel(title, self)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        if description:
            subtitle = QLabel(description, self)
            subtitle.setObjectName("PageSubtitle")
            subtitle.setWordWrap(True)
            layout.addWidget(subtitle)

        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 2, 0, 0)
        self.content_layout.setSpacing(8)
        layout.addLayout(self.content_layout)


def style_dialog_buttons(
    button_box: QDialogButtonBox,
    primary_button: QDialogButtonBox.StandardButton | None = None,
) -> None:
    for button in button_box.buttons():
        is_primary = (
            primary_button is not None
            and button_box.standardButton(button) == primary_button
        )
        button.setObjectName("PrimaryButton" if is_primary else "QuietButton")


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._position = 1.0 if self.isChecked() else 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_position)
        self.toggled.connect(self._animate_to_state)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hitButton(self, position: QPoint) -> bool:  # noqa: N802
        return self.rect().contains(position)

    def sizeHint(self):  # noqa: N802
        return QSize(280, self.heightForWidth(280))

    def minimumSizeHint(self):  # noqa: N802
        return QSize(160, self.heightForWidth(160))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        metrics = QFontMetrics(self.font())
        text_bounds = metrics.boundingRect(
            QRect(0, 0, max(1, width - 56), 1000),
            Qt.TextFlag.TextWordWrap,
            self.text(),
        )
        return max(36, text_bounds.height() + 8)

    def _animate_to_state(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _set_position(self, value: object) -> None:
        self._position = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = QRectF(2.0, (self.height() - 20.0) / 2.0, 40.0, 20.0)
        if not self.isEnabled():
            track_color = QColor("#3a3a3a")
            thumb_color = QColor("#777777")
            text_color = QColor("#8a8a8a")
        else:
            accent = system_accent_color()
            track_color = accent if self.isChecked() else QColor("#555555")
            if self.underMouse() and not self.isChecked():
                track_color = QColor("#686868")
            thumb_color = QColor("#ffffff")
            text_color = QColor("#ffffff")

        track_path = QPainterPath()
        track_path.addRoundedRect(track, 10.0, 10.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(track_path, track_color)

        thumb_size = 16.0
        thumb_x = track.left() + 2.0 + (track.width() - thumb_size - 4.0) * self._position
        thumb = QRectF(
            thumb_x,
            track.top() + (track.height() - thumb_size) / 2.0,
            thumb_size,
            thumb_size,
        )
        painter.setBrush(thumb_color)
        painter.drawEllipse(thumb)

        if self.hasFocus() and self.isEnabled():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(system_accent_color(), 1.0))
            painter.drawRoundedRect(track.adjusted(-1.0, -1.0, 1.0, 1.0), 11.0, 11.0)

        painter.setPen(text_color)
        text_rect = QRectF(54.0, 0.0, max(0.0, self.width() - 56.0), float(self.height()))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
            | Qt.TextFlag.TextWordWrap,
            self.text(),
        )
