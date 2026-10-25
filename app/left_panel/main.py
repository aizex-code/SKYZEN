from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QSize, Signal, QMimeData, QFileInfo
from PySide6.QtGui import QDrag, QIcon, QPixmap, QPainter, QPen, QColor, QImageReader
from app.media.thumbnail_service import ThumbnailService
from app.left_toolbar.catalog import TOOL_ORDER, TOOL_COLORS
from app.left_toolbar.library import ToolLibrary

from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QFileIconProvider,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QMenu,
    QVBoxLayout,
    QWidget,
)


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg"}

TOOL_COLORS = {
    "Media": "#00D5EE",
    "Audio": "#6F91FF",
    "Text": "#B27CFF",
    "Stickers": "#E9A044",
    "Effects": "#F2A44A",
    "Transitions": "#57AEFF",
    "Filters": "#5CB8FF",
    "Adjustment": "#54C995",
    "Adjustments": "#54C995",
}


def kind_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "Video"
    if ext in IMAGE_EXTS:
        return "Image"
    if ext in AUDIO_EXTS:
        return "Audio"
    return "Media"


def ffmpeg_binary(root_dir: Path, name: str) -> Path | None:
    """Find bundled FFmpeg first, then use the Windows/PATH installation."""
    candidates = [
        root_dir / "ffmpeg" / name,
        root_dir / name,
        root_dir / "bin" / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    # Some installations expose ffmpeg without the .exe suffix.
    if name.lower().endswith(".exe"):
        found = shutil.which(name[:-4])
        if found:
            return Path(found)
    return None


def duration_seconds(path: Path, root_dir: Path) -> float:
    ffprobe = ffmpeg_binary(root_dir, "ffprobe.exe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [
                str(ffprobe), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return max(0.0, float((result.stdout or "").strip()))
    except Exception:
        return 0.0


def make_video_thumbnail(path: Path, root_dir: Path) -> QPixmap:
    ffmpeg = ffmpeg_binary(root_dir, "ffmpeg.exe")
    if not ffmpeg:
        return QPixmap()

    cache_dir = root_dir / "cache" / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{path.stem}_{abs(hash(str(path))) & 0xffffffff:x}.jpg"

    if not cache.exists():
        try:
            subprocess.run(
                [
                    str(ffmpeg), "-y", "-ss", "0.25",
                    "-i", str(path),
                    "-frames:v", "1",
                    "-vf", "scale=320:-2",
                    str(cache),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            return QPixmap()

    return QPixmap(str(cache)) if cache.exists() else QPixmap()


def audio_thumbnail(path: Path) -> QPixmap:
    pix = QPixmap(126, 74)
    pix.fill(QColor("#25105A"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#00D5EE"), 1))
    seed = max(1, sum(path.name.encode("utf-8")))
    mid = pix.height() // 2
    for x in range(2, pix.width() - 2, 3):
        amp = 4 + abs(((x * 19 + seed) % 33) - 16)
        painter.drawLine(x, mid - amp, x, mid + amp)
    painter.end()
    return pix


def rounded_cover(pix: QPixmap, w: int, h: int, radius: int = 8) -> QPixmap:
    """Scale to fill w x h (centre crop) with rounded corners, like CapCut."""
    from PySide6.QtGui import QPainterPath
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    if pix is None or pix.isNull():
        return out
    scaled = pix.scaled(
        w, h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, w, h, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    painter.end()
    return out


class AssetCard(QFrame):
    preview_requested = Signal(str, str)
    add_requested = Signal(str, str)
    remove_requested = Signal(str)

    def __init__(self, path: Path, kind: str, root_dir: Path, parent=None, thumbnail_service=None):
        super().__init__(parent)
        self.path = path
        self.kind = kind
        self.root_dir = root_dir
        self.thumbnail_service = thumbnail_service
        self.drag_origin = QPoint()

        self.setObjectName("AssetCard")
        self.setFixedSize(128, 104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setStyleSheet(f"""
            QFrame#AssetCard {{
                background:transparent;
                border:1px solid transparent;
                border-radius:10px;
            }}
            QFrame#AssetCard:hover {{
                border:1px solid #3F4650;
                background:#2A2C30;
            }}
            QLabel {{
                background:transparent;
                border:0;
            }}
            QToolButton {{
                background:#292929;
                color:#EEEEEE;
                border:1px solid #252E3A;
                border-radius:4px;
            }}
            QToolButton:hover {{
                border-color:{TOOL_COLORS.get(kind, "#00D5EE")};
                color:{TOOL_COLORS.get(kind, "#00D5EE")};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(5, 4, 5, 4)
        root.setSpacing(2)

        self.icon_provider = QFileIconProvider()
        self.file_icon = self.icon_provider.icon(QFileInfo(str(path)))
        self.thumb = QLabel()
        self.thumb.setFixedHeight(52)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        pix = self.make_thumb()
        if not pix.isNull():
            self.thumb.setPixmap(rounded_cover(pix, 116, 52, 7))
        else:
            icon_pixmap = self.file_icon.pixmap(40, 40)
            if not icon_pixmap.isNull():
                self.thumb.setPixmap(icon_pixmap)
            else:
                self.thumb.setText(kind.upper())
                self.thumb.setStyleSheet("color:#8793A2;")

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        type_icon = QLabel()
        type_icon.setFixedSize(16, 16)
        small_icon = self.file_icon.pixmap(16, 16)
        if not small_icon.isNull():
            type_icon.setPixmap(small_icon)
        name = QLabel(path.name)
        name.setToolTip(str(path))
        name.setWordWrap(False)
        name.setMinimumWidth(0)
        title_row.addWidget(type_icon, 0)
        title_row.addWidget(name, 1)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(4)
        meta = QLabel(self.meta_text())
        meta.setStyleSheet("color:#A0A0A0; font-size:9px;")
        meta_row.addWidget(meta, 1)

        # The add action sits beside the asset metadata, not over the preview,
        # so the thumbnail stays clear and the control is easy to discover.
        self.thumb.setObjectName("AssetThumbnail")
        self.thumb.setStyleSheet("QLabel#AssetThumbnail{background:#17191D;border-radius:7px;}")
        self.plus_button = QToolButton(self)
        self.plus_button.setText("+")
        self.plus_button.setFixedSize(28, 22)
        self.plus_button.setToolTip("Add to a new compatible timeline layer at the playhead")
        self.plus_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plus_button.setStyleSheet(
            "QToolButton{background:#252B32;color:#FFFFFF;"
            "border:1px solid #46515D;border-radius:6px;"
            "font-size:19px;font-weight:700;padding:0;margin:0;}"
            "QToolButton:hover{background:#00D8E8;color:#06222A;border-color:#00D8E8;}"
        )
        self.plus_button.clicked.connect(lambda: self.add_requested.emit(str(self.path), self.kind))
        meta_row.addWidget(self.plus_button, 0, Qt.AlignmentFlag.AlignRight)

        root.addWidget(self.thumb)
        root.addLayout(title_row)
        root.addLayout(meta_row)

    def make_thumb(self) -> QPixmap:
        if self.kind == "Image":
            try:
                reader = QImageReader(str(self.path))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    size.scale(320, 180, Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(size)
                return QPixmap.fromImage(reader.read())
            except Exception:
                return QPixmap(str(self.path))
        if self.kind == "Video":
            if self.thumbnail_service is not None:
                return self.thumbnail_service.request(self.path)
            # Fallback for cards created outside the main editor integration.
            return make_video_thumbnail(self.path, self.root_dir)
        if self.kind == "Audio":
            return audio_thumbnail(self.path)
        return QPixmap()

    def set_thumbnail(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            return
        self.thumb.setPixmap(rounded_cover(pixmap, 116, 40, 7))
        self.thumb.setText("")

    def meta_text(self) -> str:
        # Never launch ffprobe from card construction: rebuilding the media
        # grid must not block the UI while a drive or codec is slow.
        return self.kind.lower()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.position().toPoint()
            self._drag_started = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Preview only on a click. Starting a drag must not switch the player
        # to a separate source preview while the user is placing a clip.
        if (event.button() == Qt.MouseButton.LeftButton
                and not getattr(self, "_drag_started", False)):
            self.preview_requested.emit(str(self.path), self.kind)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        preview = menu.addAction("Preview")
        add = menu.addAction("Add to Timeline")
        menu.addSeparator()
        remove = menu.addAction("Remove from Media Bin")
        action = menu.exec(event.globalPos())
        if action == preview:
            self.preview_requested.emit(str(self.path), self.kind)
        elif action == add:
            self.add_requested.emit(str(self.path), self.kind)
        elif action == remove:
            # This only removes the library entry from Skyzen; it never deletes
            # the user's original file from disk.
            self.remove_requested.emit(str(self.path))
        event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        distance = (
            event.position().toPoint() - self.drag_origin
        ).manhattanLength()
        if distance < 8:
            return

        self._drag_started = True
        mime = QMimeData()
        mime.setData(
            "application/x-skyzen-media",
            f"{self.kind}|{self.path}".encode("utf-8"),
        )
        mime.setText(str(self.path))

        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = self.thumb.pixmap()
        if pix and not pix.isNull():
            drag.setPixmap(pix.scaled(100, 60, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.FastTransformation))
            drag.setHotSpot(QPoint(50, 30))
        drag.exec(Qt.DropAction.CopyAction)


class LeftPanel(QFrame):
    preview_requested = Signal(str, str)
    add_requested = Signal(str, str)
    add_tool_requested = Signal(str, str)
    media_imported = Signal(str)

    def __init__(self, root_dir: Path, parent=None, thumbnail_service=None):
        super().__init__(parent)
        self.root_dir = root_dir
        self.thumbnail_service = thumbnail_service or ThumbnailService(root_dir, self)
        self.thumbnail_service.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.setObjectName("Panel")
        self.current_tool = "Media"
        self.cards = []
        self.current_folder = None
        self.browser_source = "folder"
        self.imported_items = []
        self.folder_items = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(2)

        # Compact CapCut-inspired tool row. All five tools fit at normal width;
        # the overflow menu appears automatically for narrow left panels.
        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(0, 0, 0, 0)
        tool_row.setSpacing(3)
        symbols = {"Media": "▧", "Audio": "♫", "Text": "T", "Effects": "✦", "Filters": "◈", "Adjustments": "◉"}
        self.tool_buttons = {}
        for name in TOOL_ORDER:
            button = QToolButton()
            button.setText(f"{symbols[name]}\n{name if name != 'Adjustments' else 'Adjust'}")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setFixedSize(46, 50)
            button.setToolTip(name)
            button.setCheckable(True)
            button.setChecked(name == "Media")
            color = TOOL_COLORS[name]
            button.setStyleSheet(f"""
                QToolButton {{ background:transparent; color:#A4ADB8; border:1px solid transparent;
                    border-radius:6px; padding:2px; font-size:10px; }}
                QToolButton:hover {{ color:#F3F6F9; border-color:{color}; background:#292D32; }}
                QToolButton:checked {{ color:{color}; border-color:{color}; background:#252A30; }}
            """)
            button.clicked.connect(lambda checked=False, n=name: self.select_tool(n))
            tool_row.addWidget(button)
            self.tool_buttons[name] = button

        self.more_tools_button = QToolButton()
        self.more_tools_button.setText("›")
        self.more_tools_button.setFixedSize(22, 50)
        self.more_tools_button.setToolTip("More tools")
        self.more_tools_menu = QMenu(self.more_tools_button)
        for name in ("Text", "Effects", "Filters", "Adjustments"):
            action = self.more_tools_menu.addAction(name)
            action.triggered.connect(lambda checked=False, n=name: self.select_tool(n))
        self.more_tools_button.setMenu(self.more_tools_menu)
        self.more_tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_tools_button.setStyleSheet("QToolButton{color:#D7DEE6;background:#252A30;border:1px solid #3A414A;border-radius:5px;font-size:20px;}QToolButton:hover{color:#00D5EE;border-color:#00D5EE;}")
        self.more_tools_button.hide()
        tool_row.addWidget(self.more_tools_button)
        outer.addLayout(tool_row)

        self.media_body = QWidget(self)
        body = QHBoxLayout(self.media_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        rail = QFrame()
        rail.setFixedWidth(88)
        rail.setStyleSheet(
            "QFrame{background:#222222; border-right:1px solid #3A3A3A;}"
        )
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(3, 3, 3, 3)
        rail_layout.setSpacing(4)

        import_button = QPushButton("Import⌄")
        import_button.setObjectName("ImportButton")
        import_button.clicked.connect(self.import_files)
        import_button.setStyleSheet(
            "QPushButton#ImportButton{border-color:#00D5EE;}"
        )
        rail_layout.addWidget(import_button)

        self.yours_button = QPushButton("Yours")
        self.yours_button.setToolTip("Show media imported into Skyzen")
        self.yours_button.clicked.connect(self.show_yours)
        rail_layout.addWidget(self.yours_button)

        browse_button = QPushButton("Folder…")
        browse_button.setToolTip("Browse a folder like a file explorer")
        browse_button.clicked.connect(self.browse_folder)
        rail_layout.addWidget(browse_button)

        refresh_button = QPushButton("Refresh")
        refresh_button.setToolTip("Rescan the current folder")
        refresh_button.clicked.connect(self.refresh_folder)
        rail_layout.addWidget(refresh_button)

        collection_label = QLabel("Media bin")
        collection_label.setWordWrap(True)
        collection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        collection_label.setStyleSheet("color:#A0A0A0; font-size:10px;")
        rail_layout.addWidget(collection_label)
        rail_layout.addStretch()

        body.addWidget(rail)

        browser = QFrame()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(1, 2, 2, 0)
        browser_layout.setSpacing(4)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕  Search media...")
        self.search.textChanged.connect(self.rebuild)
        top.addWidget(self.search, 1)

        view = QToolButton()
        view.setText("◫")
        view.setToolTip("Media view")
        top.addWidget(view)
        browser_layout.addLayout(top)

        self.folder_path_label = QLabel("Imported media")
        self.folder_path_label.setToolTip("Current media folder")
        self.folder_path_label.setStyleSheet(
            "color:#A0A0A0; padding-left:2px; font-size:10px;"
        )
        self.folder_path_label.setWordWrap(False)
        browser_layout.addWidget(self.folder_path_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(6, 12, 6, 16)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(10)
        self.scroll.setWidget(self.grid_host)
        browser_layout.addWidget(self.scroll, 1)

        body.addWidget(browser, 1)
        outer.addWidget(self.media_body, 1)

        self.tool_library = ToolLibrary(self.root_dir, self)
        self.tool_library.add_requested.connect(self.add_tool_requested)
        outer.addWidget(self.tool_library, 1)
        self.tool_library.hide()

        self.items = []
        self.scan_demo_assets()
        self._update_tool_overflow()

    def select_tool(self, name: str):
        if name not in TOOL_ORDER:
            return
        self.current_tool = name
        for key, button in self.tool_buttons.items():
            button.setChecked(key == name)
        media_mode = name in {"Media", "Audio"}
        self.tool_library.setVisible(not media_mode)
        # The existing media browser and rail are untouched; tool libraries use
        # the full panel width so preset cards are not squeezed into a tiny column.
        for child in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if child is not self.tool_library:
                # The outer layout contains the old media body as a QLayout, so
                # visibility is toggled explicitly below instead of recursively.
                pass
        self._media_body_visible(media_mode)
        if media_mode:
            self.search.setPlaceholderText("⌕  Search audio..." if name == "Audio" else "⌕  Search media...")
            self.rebuild()
        else:
            self.tool_library.set_tool(name)

    def _media_body_visible(self, visible: bool):
        self.media_body.setVisible(bool(visible))

    def _update_tool_overflow(self):
        narrow = self.width() < 282
        self.more_tools_button.setVisible(narrow)
        if narrow:
            for name in ("Text", "Effects", "Filters", "Adjustments"):
                self.tool_buttons[name].hide()
        else:
            for name in TOOL_ORDER:
                self.tool_buttons[name].show()

    def scan_demo_assets(self):
        self.items = []
        self.folder_items = []
        self.browser_source = "folder"
        demo = self.root_dir / "demo_assets"
        if demo.is_dir():
            self.current_folder = demo
            self._scan_folder_into_items(demo, clear=True)
            self.folder_path_label.setText(str(demo))
        else:
            self.folder_path_label.setText("Imported media — choose Folder…")
            self.rebuild()

    def _scan_folder_into_items(self, folder: Path, clear=False):
        """Load one folder as a separate browser source; never crawl a drive."""
        if clear:
            self.folder_items = []
        try:
            paths = sorted(
                (p for p in folder.iterdir() if p.is_file() and p.suffix.lower()
                 in (VIDEO_EXTS | IMAGE_EXTS | AUDIO_EXTS)),
                key=lambda p: p.name.lower(),
            )
        except (OSError, PermissionError):
            paths = []

        existing = {str(p.resolve()).lower() for p, _kind in self.folder_items}
        for path in paths:
            try:
                key = str(path.resolve()).lower()
            except (OSError, RuntimeError):
                key = str(path).lower()
            if key not in existing:
                self.folder_items.append((path, kind_for(path)))
                existing.add(key)
        self.folder_items.sort(key=lambda pair: pair[0].name.lower())
        if self.browser_source == "folder":
            self.items = list(self.folder_items)
            self.folder_path_label.setText(str(folder))
        self.rebuild()

    def show_yours(self):
        """Show only assets explicitly imported into the current Skyzen session."""
        self.browser_source = "yours"
        self.items = list(self.imported_items)
        self.folder_path_label.setText("Yours · imported media")
        self.yours_button.setStyleSheet("QPushButton{border-color:#00D5EE;color:#00D5EE;}")
        self.rebuild()

    def browse_folder(self):
        start = str(self.current_folder or Path.home())
        folder = QFileDialog.getExistingDirectory(
            self,
            "Browse Media Folder",
            start,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return
        self.current_folder = Path(folder)
        self.browser_source = "folder"
        self.yours_button.setStyleSheet("")
        # Browsing a folder is isolated from the imported-media collection.
        self._scan_folder_into_items(self.current_folder, clear=True)

    def refresh_folder(self):
        if self.browser_source == "yours":
            self.items = list(self.imported_items)
            self.rebuild()
            return
        if self.current_folder and self.current_folder.is_dir():
            self.folder_path_label.setText(str(self.current_folder))
            self._scan_folder_into_items(self.current_folder, clear=True)
        else:
            self.rebuild()

    def clear_cards(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.cards.clear()

    def rebuild(self, *_):
        self.clear_cards()

        needle = self.search.text().strip().lower()
        matches = []

        for path, kind in self.items:
            if self.current_tool == "Audio" and kind != "Audio":
                continue
            if self.current_tool not in {"Media", "Audio"}:
                continue

            if needle and needle not in path.name.lower():
                continue
            matches.append((path, kind))

        # CapCut-like responsive media bin: use two columns in a narrow
        # browser and three only when the available content width supports it.
        viewport_width = max(1, self.scroll.viewport().width())
        columns = max(1, min(3, viewport_width // 134))
        for index, (path, kind) in enumerate(matches):
            card = AssetCard(path, kind, self.root_dir, self.grid_host, self.thumbnail_service)
            card.preview_requested.connect(self.preview_requested)
            card.add_requested.connect(self.add_requested)
            card.remove_requested.connect(self.remove_imported_media)
            self.grid.addWidget(card, index // columns, index % columns)
            self.cards.append(card)

        self.grid.setRowStretch((len(matches) // columns) + 1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_tool_overflow()
        try:
            columns = max(1, min(3, max(1, self.scroll.viewport().width()) // 134))
            if columns != getattr(self, "_last_grid_columns", None):
                self._last_grid_columns = columns
                self.rebuild()
        except Exception:
            pass

    def _on_thumbnail_ready(self, source_path: str, pixmap: QPixmap):
        if pixmap.isNull():
            return
        try:
            source_key = str(Path(source_path).resolve()).lower()
        except (OSError, RuntimeError):
            source_key = str(source_path).lower()
        for card in tuple(self.cards):
            try:
                if str(card.path.resolve()).lower() == source_key:
                    card.set_thumbnail(pixmap)
            except (OSError, RuntimeError):
                continue

    def remove_imported_media(self, path: str):
        """Remove an item from the media bin without deleting the source file."""
        try:
            target = Path(path).resolve()
            self.imported_items = [
                (item_path, kind) for item_path, kind in self.imported_items
                if item_path.resolve() != target
            ]
            if self.browser_source == "yours":
                self.items = list(self.imported_items)
            else:
                self.items = [
                    (item_path, kind) for item_path, kind in self.items
                    if item_path.resolve() != target
                ]
        except (OSError, RuntimeError):
            return
        self.rebuild()

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Media",
            str(Path.home()),
            "Media (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.wmv "
            "*.png *.jpg *.jpeg *.gif *.bmp *.webp "
            "*.wav *.mp3 *.flac *.aac *.m4a *.ogg);;All files (*.*)",
        )
        if not files:
            return

        for value in files:
            path = Path(value)
            if path.is_file():
                try:
                    key = str(path.resolve()).lower()
                    exists = any(str(item.resolve()).lower() == key for item, _kind in self.imported_items)
                except (OSError, RuntimeError):
                    exists = any(item == path for item, _kind in self.imported_items)
                if not exists:
                    entry = (path, kind_for(path))
                    self.imported_items.append(entry)
                    self.media_imported.emit(str(path.resolve()))

        self.imported_items.sort(key=lambda pair: pair[0].name.lower())
        self.browser_source = "yours"
        self.items = list(self.imported_items)
        self.yours_button.setStyleSheet("QPushButton{border-color:#00D5EE;color:#00D5EE;}")
        self.folder_path_label.setText("Yours · imported media")
        self.rebuild()
