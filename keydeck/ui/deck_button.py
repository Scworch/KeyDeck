from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class SquircleButton(QPushButton):
    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self._size = size
        self._radius = max(14, int(size * 0.28))
        self._avatar = QPixmap()
        self._avatar_mode = "cover"
        self._avatar_zoom = 1.0
        self._avatar_offset_x = 0
        self._avatar_offset_y = 0
        self._show_plus = False
        self._drop_target = False

    def set_show_plus(self, show: bool) -> None:
        self._show_plus = bool(show)
        self.update()

    def set_drop_target(self, is_target: bool) -> None:
        self._drop_target = bool(is_target)
        self.update()

    def set_avatar(
        self,
        icon_path: str | None,
        icon_mode: str = "default",
        icon_zoom: float = 1.0,
        icon_offset_x: int = 0,
        icon_offset_y: int = 0,
    ) -> None:
        self._avatar_zoom = max(0.2, min(icon_zoom, 3.0))
        self._avatar_offset_x = int(icon_offset_x)
        self._avatar_offset_y = int(icon_offset_y)

        if not icon_path:
            self._avatar = QPixmap()
            self._avatar_mode = "cover"
        else:
            # For .ico files, QIcon picks the best embedded size variant.
            icon = QIcon(icon_path)
            if not icon.isNull():
                wanted = max(256, self._size * 4)
                pix = icon.pixmap(wanted, wanted)
                source = pix if not pix.isNull() else QPixmap(icon_path)
            else:
                source = QPixmap(icon_path)
            self._avatar = self._normalize_pixmap(self._trim_transparent_padding(source))
            if icon_mode == "centered":
                self._avatar_mode = "centered"
            else:
                self._avatar_mode = "contain" if icon_path.lower().endswith(".ico") else "cover"
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        self._pressed = True
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self._pressed = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        # Enforce strict 1:1 square aspect ratio geometry centered inside widget bounds
        side = max(10, min(self.width(), self.height()) - 2)
        rect = QRectF(0.0, 0.0, float(side), float(side))
        rect.moveCenter(QPointF(self.width() / 2.0, self.height() / 2.0))

        radius = max(10.0, float(side * 0.28))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        bg_color = QColor("#222222") if self._show_plus else QColor("#2a2a2a")
        painter.fillPath(path, bg_color)

        if self._show_plus and self._avatar.isNull():
            # Draw sleek plus icon for empty slots
            painter.setClipping(False)
            pen_color = QColor("#ffffff") if self._hovered else QColor("#666666")
            pen = QPen(pen_color, max(2.0, float(side * 0.06)))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            cx, cy = rect.center().x(), rect.center().y()
            arm = float(side * 0.16)
            painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
            painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
            painter.setClipPath(path)

        if not self._avatar.isNull():
            if self._avatar_mode == "centered":
                # Dedicated mode: keep icon compact and strictly centered.
                scaled = self._normalize_pixmap(self._avatar.scaled(
                    int(rect.width() * 0.74 * self._avatar_zoom),
                    int(rect.height() * 0.74 * self._avatar_zoom),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                ))
            elif self._avatar_mode == "contain":
                # .ico game icons should stay centered without aggressive crop.
                scaled = self._normalize_pixmap(self._avatar.scaled(
                    int(rect.width() * 0.9 * self._avatar_zoom),
                    int(rect.height() * 0.9 * self._avatar_zoom),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                ))
            else:
                # Cover scaling: fill full button and crop overflow in clipped shape.
                scaled = self._normalize_pixmap(self._avatar.scaled(
                    int(rect.width() * 1.18 * self._avatar_zoom),
                    int(rect.height() * 1.18 * self._avatar_zoom),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                ))
            target = QRectF(0.0, 0.0, float(scaled.width()), float(scaled.height()))
            target.moveCenter(
                QPointF(
                    rect.center().x() + self._avatar_offset_x,
                    rect.center().y() + self._avatar_offset_y,
                )
            )
            source = QRectF(0.0, 0.0, float(scaled.width()), float(scaled.height()))
            painter.drawPixmap(target, scaled, source)

        # Hover/press dim overlay goes on top of icon/background alike.
        if self._pressed:
            painter.fillPath(path, QColor(0, 0, 0, 110))
        elif self._hovered:
            painter.fillPath(path, QColor(0, 0, 0, 70))

        painter.setClipping(False)
        border_pen = QPen(QColor("#0078d4"), 2) if self._drop_target else QPen(QColor("#3a3a3a"), 1)
        painter.setPen(border_pen)
        painter.drawPath(path)



    def _trim_transparent_padding(self, pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return QPixmap()
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)

        left = image.width()
        right = -1
        top = image.height()
        bottom = -1

        for y in range(image.height()):
            for x in range(image.width()):
                alpha = QColor.fromRgba(image.pixel(x, y)).alpha()
                if alpha > 0:
                    left = min(left, x)
                    right = max(right, x)
                    top = min(top, y)
                    bottom = max(bottom, y)

        if right < left or bottom < top:
            return pixmap

        return pixmap.copy(left, top, right - left + 1, bottom - top + 1)

    def _normalize_pixmap(self, pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return QPixmap()
        normalized = QPixmap.fromImage(pixmap.toImage())
        normalized.setDevicePixelRatio(1.0)
        return normalized


class DeckButtonWidget(QWidget):
    clicked = Signal(int)

    def __init__(
        self,
        index: int,
        title: str,
        size: int,
        icon_path: str | None = None,
        icon_mode: str = "default",
        icon_zoom: float = 1.0,
        icon_offset_x: int = 0,
        icon_offset_y: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._index = index

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.button = SquircleButton(size=size, parent=self)
        self.button.clicked.connect(self._emit_click)
        self.button.setCursor(Qt.PointingHandCursor)
        self._apply_icon(
            icon_path,
            icon_mode,
            icon_zoom=icon_zoom,
            icon_offset_x=icon_offset_x,
            icon_offset_y=icon_offset_y,
        )

        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.label.setWordWrap(False)
        self.label.setStyleSheet("color: #d8d8d8; font-size: 10px;")
        self.label.setFixedWidth(size)
        self.set_title(title)

        layout.addWidget(self.button, alignment=Qt.AlignHCenter)
        layout.addWidget(self.label, alignment=Qt.AlignHCenter)

    def set_title(self, title: str) -> None:
        metrics = QFontMetrics(self.label.font())
        elided = metrics.elidedText(title, Qt.ElideRight, self.label.width())
        self.label.setText(elided)

    def _emit_click(self) -> None:
        self.clicked.emit(self._index)

    def _apply_icon(
        self,
        icon_path: str | None,
        icon_mode: str = "default",
        icon_zoom: float = 1.0,
        icon_offset_x: int = 0,
        icon_offset_y: int = 0,
    ) -> None:
        self.button.set_avatar(
            icon_path,
            icon_mode=icon_mode,
            icon_zoom=icon_zoom,
            icon_offset_x=icon_offset_x,
            icon_offset_y=icon_offset_y,
        )
