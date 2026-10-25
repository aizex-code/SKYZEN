from __future__ import annotations
import json
from PySide6.QtCore import Qt, QPoint, QSize, Signal, QMimeData, QEvent
from PySide6.QtGui import QColor, QDrag, QPainter, QPen, QFont, QLinearGradient
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QSizePolicy
from .catalog import TOOL_COLORS

class PresetCard(QFrame):
    add_requested = Signal(str, str)
    def __init__(self, tool_type: str, preset: dict, parent=None):
        super().__init__(parent)
        self.tool_type = tool_type
        self.preset = dict(preset)
        self._drag_origin = QPoint()
        accent = TOOL_COLORS[tool_type]
        self.setObjectName("ToolPresetCard")
        self.setMinimumSize(104, 104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame#ToolPresetCard {{ background:#25282D; border:1px solid #363C44; border-radius:9px; }}
            QFrame#ToolPresetCard:hover {{ background:#2C3036; border:1px solid {accent}; }}
            QLabel {{ background:transparent; border:0; }}
            QToolButton {{ background:#202329; color:#F4F6F8; border:1px solid #48515D; border-radius:6px; font-size:19px; font-weight:700; }}
            QToolButton:hover {{ background:{accent}; color:#11151A; border-color:{accent}; }}
        """)
        root = QVBoxLayout(self); root.setContentsMargins(4,4,4,4); root.setSpacing(3)
        preview_frame = QFrame(); preview_frame.setFixedHeight(54)
        preview_frame.setStyleSheet("QFrame{background:#171B20;border:0;border-radius:6px;}")
        preview_grid = __import__('PySide6.QtWidgets', fromlist=['QGridLayout']).QGridLayout(preview_frame)
        preview_grid.setContentsMargins(0,0,0,0); preview_grid.setSpacing(0)
        self.preview = QLabel(); self.preview.setMinimumWidth(0)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setScaledContents(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setMinimumSize(0, 0)
        self.preview.setPixmap(self._make_preview(220, 108))
        preview_grid.addWidget(self.preview, 0, 0)
        self.plus = QToolButton(); self.plus.setText("+"); self.plus.setFixedSize(24,23)
        self.plus.setToolTip(f"Add {preset.get('name', tool_type)} to the timeline at the playhead")
        self.plus.setStyleSheet(f"QToolButton{{background:#202329;color:#FFFFFF;border:1px solid {accent};border-radius:6px;font-size:20px;font-weight:700;}}QToolButton:hover{{background:{accent};color:#11151A;}}")
        self.plus.clicked.connect(lambda: self.add_requested.emit(self.tool_type, str(self.preset["id"])))
        preview_grid.addWidget(self.plus, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        root.addWidget(preview_frame)
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(4)
        text_col = QVBoxLayout(); text_col.setSpacing(1)
        self.title = QLabel(str(preset.get("name", tool_type)))
        self.title.setStyleSheet("color:#F0F3F6;font-size:10px;font-weight:650;")
        self.title.setWordWrap(False)
        self.subtitle = QLabel(str(preset.get("subtitle", "")))
        self.subtitle.setStyleSheet("color:#939EAA;font-size:8px;")
        self.subtitle.setWordWrap(False)
        text_col.addWidget(self.title); text_col.addWidget(self.subtitle)
        row.addLayout(text_col, 1)
        root.addLayout(row)
        # Child labels otherwise consume mouse movement and prevent the parent
        # card's drag gesture from starting. The + button remains independently clickable.
        for surface in (preview_frame, self.preview, self.title, self.subtitle):
            surface.installEventFilter(self)

    def _make_preview(self, width, height):
        accent = QColor(TOOL_COLORS[self.tool_type])
        pix = __import__('PySide6.QtGui', fromlist=['QPixmap']).QPixmap(width, height)
        grad = QLinearGradient(0, 0, width, height)
        grad.setColorAt(0, QColor("#15191F")); grad.setColorAt(1, QColor("#303740"))
        p = QPainter(pix); p.fillRect(0,0,width,height,grad)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 150), 1))
        p.drawRoundedRect(8,8,width-16,height-16,8,8)
        p.setPen(accent)
        font = QFont("Segoe UI", max(12, height//4)); font.setBold(True); p.setFont(font)
        symbol = {"Text":"T", "Effects":"✦", "Filters":"◈", "Adjustments":"◐"}.get(self.tool_type,"•")
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, symbol)
        if self.tool_type == "Text":
            p.setPen(QColor("#F5F7FA")); small = QFont("Segoe UI", 10); small.setBold(True); p.setFont(small)
            p.drawText(12,height-14,str(self.preset.get("text", self.preset.get("name","Title"))).replace("\n"," ")[:28])
        elif self.tool_type == "Effects":
            for i in range(4):
                p.setPen(QPen(QColor(accent.red(),accent.green(),accent.blue(),80+i*30), 3+i))
                p.drawLine(16+i*12, height-12, width-18, 12+i*8)
        else:
            p.fillRect(16, height-18, width-32, 5, QColor("#414954"))
            p.fillRect(16, height-18, int((width-32)*0.72), 5, accent)
        p.end(); return pix

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            self._drag_surface = watched
        elif event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
            if watched is getattr(self, "_drag_surface", None) and (event.position().toPoint() - self._drag_origin).manhattanLength() >= 8:
                self._start_drag()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            self._drag_surface = self
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._drag_origin).manhattanLength() >= 8:
            self._start_drag()

    def _start_drag(self):
        mime = QMimeData()
        payload = {"tool_type": self.tool_type, "preset_id": str(self.preset["id"])}
        mime.setData("application/x-skyzen-tool-asset", json.dumps(payload).encode("utf-8"))
        mime.setText(f"Skyzen {self.tool_type}: {self.preset.get('name', self.preset['id'])}")
        drag = QDrag(self); drag.setMimeData(mime)
        pix = self.preview.pixmap()
        if pix and not pix.isNull(): drag.setPixmap(pix.scaled(QSize(120,65), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)
