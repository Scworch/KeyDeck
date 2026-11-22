from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QBitmap,
    QRegion,
)
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class SquircleButton(QPushButton):
    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setObjectName("DeckKey")
        self._size = max(32, int(size))
        self._radius = max(4, int(self._size * 0.04))
        self.setStyleSheet(
            "QPushButton#DeckKey {"
            "background: transparent; border: none; padding: 0px;"
            f"min-width: {self._size}px; max-width: {self._size}px;"
            f"min-height: {self._size}px; max-height: {self._size}px;"
            "}"
        )
        self._avatar = QPixmap()
        self._scaled_avatar = QPixmap()
        self._avatar_mode = "cover"
        self._avatar_zoom = 1.0
        self._avatar_offset_x = 0
        self._avatar_offset_y = 0
        self._show_plus = False
        self._drop_target = False
        self._hovered = False
        self._pressed = False
        self.setFixedSize(self._size, self._size)
        self.setMinimumSize(self._size, self._size)
        self.setMaximumSize(self._size, self._size)

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
            self._scaled_avatar = QPixmap()
            self._avatar_mode = "cover"
        else:
            if icon_mode == "centered":
                self._avatar_mode = "centered"
            else:
                self._avatar_mode = "contain"
            path = str(Path(icon_path).resolve())
            try:
                stat = Path(path).stat()
                modified_ns, file_size = stat.st_mtime_ns, stat.st_size
            except OSError:
                modified_ns, file_size = 0, 0
            self._avatar = self._load_avatar_pixmap(
                path,
                self._size,
                modified_ns,
                file_size,
            )
            self._scaled_avatar = self._load_scaled_avatar_pixmap(
                path,
                self._size,
                modified_ns,
                file_size,
                self._avatar_mode,
                self._avatar_zoom,
            )
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
        
        w = float(self.width())
        h = float(self.height())
        rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)

        radius = float(self._radius)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        bg_color = QColor("#292929") if self._show_plus else QColor("#303030")
        painter.fillPath(path, bg_color)

        if self._show_plus and self._avatar.isNull():
            # Draw sleek plus icon for empty slots
            painter.setClipping(False)
            pen_color = QColor("#ffffff") if self._hovered else QColor("#666666")
            pen = QPen(pen_color, max(2.0, float(min(w, h) * 0.06)))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            cx, cy = rect.center().x(), rect.center().y()
            arm = float(min(w, h) * 0.16)
            painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
            painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
            painter.setClipPath(path)

        if not self._scaled_avatar.isNull():
            target = QRectF(
                0.0,
                0.0,
                float(self._scaled_avatar.width()),
                float(self._scaled_avatar.height()),
            )
            target.moveCenter(
                QPointF(
                    rect.center().x() + self._avatar_offset_x,
                    rect.center().y() + self._avatar_offset_y,
                )
            )
            source = QRectF(
                0.0,
                0.0,
                float(self._scaled_avatar.width()),
                float(self._scaled_avatar.height()),
            )
            painter.drawPixmap(target, self._scaled_avatar, source)

        # Hover/press dim overlay goes on top of icon/background alike.
        if self._pressed:
            painter.fillPath(path, QColor(0, 0, 0, 110))
        elif self._hovered:
            painter.fillPath(path, QColor(0, 0, 0, 70))

        painter.setClipping(False)
        if self._drop_target:
            painter.setPen(QPen(QColor("#60cdff"), 2))
            painter.drawPath(path)




    @staticmethod
    @lru_cache(maxsize=128)
    def _load_avatar_pixmap(
        icon_path: str,
        size: int,
        modified_ns: int,
        file_size: int,
    ) -> QPixmap:
        _ = modified_ns, file_size
        icon = QIcon(icon_path)
        if not icon.isNull():
            pixmap = icon.pixmap(max(256, size * 4), max(256, size * 4))
            source = pixmap if not pixmap.isNull() else QPixmap(icon_path)
        else:
            source = QPixmap(icon_path)
        trimmed = SquircleButton._trim_transparent_padding(source)
        return SquircleButton._normalize_pixmap(trimmed)

    @staticmethod
    @lru_cache(maxsize=256)
    def _load_scaled_avatar_pixmap(
        icon_path: str,
        size: int,
        modified_ns: int,
        file_size: int,
        icon_mode: str,
        zoom: float,
    ) -> QPixmap:
        avatar = SquircleButton._load_avatar_pixmap(
            icon_path,
            size,
            modified_ns,
            file_size,
        )
        if avatar.isNull():
            return QPixmap()

        rect_width = float(size - 2)
        rect_height = float(size - 2)
        if icon_mode == "centered":
            width, height = rect_width * 0.74 * zoom, rect_height * 0.74 * zoom
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        elif icon_mode == "contain":
            width, height = rect_width * zoom, rect_height * zoom
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
        else:
            width, height = rect_width * 1.18 * zoom, rect_height * 1.18 * zoom
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding

        return avatar.scaled(
            max(1, int(width)),
            max(1, int(height)),
            aspect_mode,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _trim_transparent_padding(pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return QPixmap()
        alpha_mask = pixmap.toImage().createAlphaMask()
        bounds = QRegion(QBitmap.fromImage(alpha_mask)).boundingRect()
        if bounds.isEmpty():
            return pixmap
        return pixmap.copy(bounds)

    @staticmethod
    def _normalize_pixmap(pixmap: QPixmap) -> QPixmap:
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
