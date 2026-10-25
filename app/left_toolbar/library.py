from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QWidget, QGridLayout
from .catalog import CATALOGS, TOOL_COLORS
from .preset_card import PresetCard

class ToolLibrary(QFrame):
    """Polished searchable library for Text, Effects and Adjustment assets."""
    add_requested = Signal(str, str)
    def __init__(self, root_dir, parent=None):
        super().__init__(parent)
        self.root_dir = root_dir
        self.current_tool = "Text"
        self.cards = []
        self.setObjectName("ToolLibrary")
        outer = QVBoxLayout(self); outer.setContentsMargins(7,6,7,4); outer.setSpacing(5)
        heading = QHBoxLayout()
        self.tool_icon = QLabel("T"); self.tool_icon.setFixedWidth(22)
        self.tool_icon.setStyleSheet("font-size:24px;font-weight:750;")
        title_col = QVBoxLayout(); title_col.setSpacing(0)
        self.title = QLabel("Text")
        self.title.setStyleSheet("font-size:16px;font-weight:700;color:#F0F3F6;")
        self.description = QLabel("Titles, subtitles and typography presets")
        self.description.setStyleSheet("font-size:9px;color:#99A3AE;")
        title_col.addWidget(self.title); title_col.addWidget(self.description)
        heading.addWidget(self.tool_icon); heading.addLayout(title_col,1)
        outer.addLayout(heading)
        top = QHBoxLayout(); top.setSpacing(5)
        self.search = QLineEdit(); self.search.setPlaceholderText("⌕  Search presets...")
        self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.rebuild)
        self.search.setStyleSheet("QLineEdit{background:#202329;border:1px solid #373E47;border-radius:6px;padding:7px;color:#E9EDF2;}QLineEdit:focus{border-color:#00D5EE;}")
        top.addWidget(self.search,1)
        outer.addLayout(top)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget(); self.grid = QGridLayout(self.host); self.grid.setContentsMargins(0,2,2,6); self.grid.setHorizontalSpacing(6); self.grid.setVerticalSpacing(6)
        self.scroll.setWidget(self.host); outer.addWidget(self.scroll,1)
        self.note = QLabel("Drag a preset to an overlay lane, or press + to add it at the playhead.")
        self.note.setWordWrap(True); self.note.setStyleSheet("font-size:8px;color:#89939E;padding:1px 0;")
        outer.addWidget(self.note)
        self.set_tool("Text")

    def set_tool(self, tool):
        if tool not in CATALOGS: return
        self.current_tool = tool
        color = TOOL_COLORS[tool]
        self.title.setText(tool)
        self.tool_icon.setText({"Text":"T","Effects":"✦","Filters":"◈","Adjustments":"◐"}[tool])
        self.tool_icon.setStyleSheet(f"font-size:24px;font-weight:750;color:{color};")
        self.description.setText({"Text":"One clean title preset to start with","Effects":"Blur, shake, glow and vignette","Filters":"Color looks applied as editable timeline layers","Adjustments":"Project-wide or local color grading layer"}[tool])
        self.search.setPlaceholderText(f"⌕  Search {tool.lower()} presets...")
        self.rebuild()

    def rebuild(self, *_):
        while self.grid.count():
            item = self.grid.takeAt(0); w = item.widget()
            if w: w.deleteLater()
        self.cards = []
        needle = self.search.text().strip().casefold()
        items = [p for p in CATALOGS.get(self.current_tool, ()) if not needle or needle in (p.get("name","")+" "+p.get("subtitle","")).casefold()]
        width = max(1, self.scroll.viewport().width())
        columns = 3 if width >= 390 else (2 if width >= 218 else 1)
        for i, preset in enumerate(items):
            card = PresetCard(self.current_tool, preset, self.host)
            card.add_requested.connect(self._forward_add)
            self.grid.addWidget(card, i // columns, i % columns)
            self.cards.append(card)
        self.grid.setRowStretch((len(items) // columns) + 1, 1)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)

    def _forward_add(self, tool_type, preset_id):
        self.add_requested.emit(tool_type, preset_id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try: self.rebuild()
        except Exception: pass
