"""Realtime composite preview widget for Skyzen's editable timeline."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget


class LiveCompositeView(QWidget):
    """Paint the latest decoded frame from each active visual timeline clip."""

    CANVAS_WIDTH = 1280
    CANVAS_HEIGHT = 720

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1, 1)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background:#000000;")
        self._layers: list[dict] = []
        self._frames: dict[int, QImage] = {}
        self._images: dict[int, QImage] = {}

    def set_layers(self, layers: list[dict]):
        self._layers = list(layers)
        live_keys = {id(clip) for clip in self._layers}
        self._frames = {key: value for key, value in self._frames.items() if key in live_keys}
        self._images = {key: value for key, value in self._images.items() if key in live_keys}
        for clip in self._layers:
            key = id(clip)
            if str(clip.get("kind", "Video")).lower() == "image" and key not in self._images:
                image = QImage(str(clip.get("path", "")))
                if not image.isNull():
                    self._images[key] = image
        self.update()

    def set_frame(self, clip_key: int, image: QImage):
        if image is None or image.isNull():
            return
        # Detach from the transient QVideoFrame before Qt releases it.
        self._frames[int(clip_key)] = image.copy()
        self.update()

    def clear(self):
        self._layers.clear()
        self._frames.clear()
        self._images.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if not self._layers:
            painter.setPen(QColor("#6F7B89"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No clip at playhead",
            )
            painter.end()
            return

        scale = min(
            max(1, self.width()) / self.CANVAS_WIDTH,
            max(1, self.height()) / self.CANVAS_HEIGHT,
        )
        canvas_w = self.CANVAS_WIDTH * scale
        canvas_h = self.CANVAS_HEIGHT * scale
        left = (self.width() - canvas_w) / 2.0
        top = (self.height() - canvas_h) / 2.0
        painter.translate(left, top)
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        for clip in self._layers:
            key = id(clip)
            image = self._images.get(key) if str(clip.get("kind", "Video")).lower() == "image" else self._frames.get(key)
            if image is None or image.isNull():
                continue

            fit_w = image.width()
            fit_h = image.height()
            if fit_w <= 0 or fit_h <= 0:
                continue
            fit_scale = min(self.CANVAS_WIDTH / fit_w, self.CANVAS_HEIGHT / fit_h)
            draw_w = fit_w * fit_scale
            draw_h = fit_h * fit_scale

            try:
                transform_scale = max(0.05, min(8.0, float(clip.get("scale", 1.0))))
                opacity = max(0.0, min(1.0, float(clip.get("opacity", 1.0))))
                x = float(clip.get("position_x", 0.0))
                y = float(clip.get("position_y", 0.0))
                rotation = float(clip.get("rotation", 0.0))
            except (TypeError, ValueError):
                transform_scale, opacity, x, y, rotation = 1.0, 1.0, 0.0, 0.0, 0.0

            painter.save()
            painter.setOpacity(opacity)
            painter.translate(self.CANVAS_WIDTH / 2 + x, self.CANVAS_HEIGHT / 2 + y)
            painter.rotate(rotation)
            painter.scale(transform_scale, transform_scale)
            target = QRectF(-draw_w / 2.0, -draw_h / 2.0, draw_w, draw_h)
            painter.drawImage(target, image)
            painter.restore()
        painter.end()
