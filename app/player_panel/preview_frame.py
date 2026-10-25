"""Aspect-preserving QLabel used for paused project-composite frames."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


class PreviewFrameLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#202020;")
        self.setMinimumSize(1, 1)

    def set_source_pixmap(self, pixmap: QPixmap):
        self._source_pixmap = QPixmap(pixmap)
        self._refresh_pixmap()

    def _refresh_pixmap(self):
        if self._source_pixmap.isNull():
            self.clear()
            return
        self.setPixmap(self._source_pixmap.scaled(
            max(1, self.contentsRect().width()),
            max(1, self.contentsRect().height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_pixmap()
