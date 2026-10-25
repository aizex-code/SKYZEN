"""CapCut-style compact project level meter: two narrow columns of stacked
segments sitting right after the time readout. Green at the bottom, warming to
orange at the top. Exact dB is in the tooltip."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .levels import MIN_DB, SEGMENT_DB, lit_segments

LIT = ("#2FC25B", "#2FC25B", "#4DC24A", "#8CC83C", "#E3A32F", "#E8742B")
DIM = "#1F3A27"


class LevelMeter(QWidget):
    COLS = 2
    SEG_W = 4.0
    SEG_H = 2.0
    GAP_X = 1.0
    GAP_Y = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = MIN_DB
        rows = len(SEGMENT_DB)
        self.setFixedSize(
            int(self.COLS * self.SEG_W + (self.COLS - 1) * self.GAP_X) + 4,
            int(rows * self.SEG_H + (rows - 1) * self.GAP_Y) + 4,
        )
        self._update_tip()

    def _update_tip(self):
        text = "-inf" if self._db <= MIN_DB + 0.5 else f"{self._db:.1f}"
        self.setToolTip(f"Project output level: {text} dB")

    def set_level(self, db: float):
        db = max(MIN_DB, min(6.0, float(db)))
        # fast attack, smooth release
        new = db if db > self._db else self._db - (self._db - db) * 0.35
        if lit_segments(new) != lit_segments(self._db) or abs(new - self._db) > 3:
            self._db = new
            self._update_tip()
            self.update()
        else:
            self._db = new

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        on = lit_segments(self._db)
        rows = len(SEGMENT_DB)
        for col in range(self.COLS):
            x = 2.0 + col * (self.SEG_W + self.GAP_X)
            for row in range(rows):
                y = 2.0 + (rows - 1 - row) * (self.SEG_H + self.GAP_Y)
                p.setBrush(QColor(LIT[row] if row < on else DIM))
                p.drawRoundedRect(QRectF(x, y, self.SEG_W, self.SEG_H), 1, 1)
        p.end()
