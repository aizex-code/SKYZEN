from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

ACCENT = "#00D9FF"


def create_marker_heads(timeline):
    """Create ruler playhead/preview heads with the neutral cyan accent."""
    timeline.marker_head = QLabel("▼", timeline.ruler_viewport)
    timeline.marker_head.setFixedSize(14, 14)
    timeline.marker_head.setAlignment(Qt.AlignmentFlag.AlignCenter)
    timeline.marker_head.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    timeline.marker_head.setStyleSheet(
        f"QLabel{{color:{ACCENT};background:transparent;border:0;font-size:10px;padding:0;}}"
    )
    timeline.marker_head.raise_()

    timeline.preview_marker_head = QLabel("◆", timeline.ruler_viewport)
    timeline.preview_marker_head.setFixedSize(14, 14)
    timeline.preview_marker_head.setAlignment(Qt.AlignmentFlag.AlignCenter)
    timeline.preview_marker_head.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    timeline.preview_marker_head.setStyleSheet(
        "QLabel{color:#8A9099;background:transparent;border:0;font-size:8px;padding:0;}"
    )
    timeline.preview_marker_head.hide()
