import sys
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QFrame, QDialog, QLineEdit,
    QMenu, QMessageBox, QInputDialog, QColorDialog, QComboBox,
    QScrollArea, QSizePolicy
)

try:
    from .settings import SettingsDialog, load_settings, save_settings, DEFAULT_SETTINGS
except ImportError:  # Allows running this module directly for debugging.
    from settings import SettingsDialog, load_settings, save_settings, DEFAULT_SETTINGS


APP_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = APP_DIR / "projects"
TRASH_DIR = APP_DIR / "trash"
PROJECTS_DIR.mkdir(exist_ok=True)
TRASH_DIR.mkdir(exist_ok=True)


class ProjectCard(QFrame):
    """Compact project tile with a preview, readable name, and actions menu."""
    menu_requested = Signal(object)

    def __init__(self, project_path: Path, serial_number=1, parent=None, project_window=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_window = project_window
        self.serial_number = serial_number
        self.setObjectName("ProjectCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(160, 118)
        self.setToolTip(f"Project {serial_number:02d}: {project_path.name}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 5)
        layout.setSpacing(4)

        self.preview = QLabel()
        self.preview.setObjectName("ProjectPreview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(62)
        self.preview.setText("SKYZEN")
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(1, 0, 0, 0)
        bottom.setSpacing(5)

        self.name_label = QLabel(project_path.name)
        self.name_label.setObjectName("ProjectName")
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.name_label.setWordWrap(False)
        self.name_label.setMinimumWidth(0)
        self.name_label.setToolTip(project_path.name)

        self.serial_label = QLabel(f"{serial_number:02d}")
        self.serial_label.setObjectName("ProjectSerial")
        self.serial_label.setAlignment(Qt.AlignCenter)
        self.serial_label.setFixedWidth(22)
        self.serial_label.setToolTip(f"Project number {serial_number}")

        self.dots = QPushButton("⋮")
        self.dots.setObjectName("ProjectDots")
        self.dots.setFixedSize(25, 25)
        self.dots.setToolTip("Project actions")
        self.dots.clicked.connect(lambda: self.menu_requested.emit(self))

        bottom.addWidget(self.serial_label)
        bottom.addWidget(self.name_label, 1)
        bottom.addWidget(self.dots)
        layout.addWidget(self.preview)
        layout.addLayout(bottom)
        self.load_preview()

    def load_preview(self):
        image = self.project_path / "thumbnail.png"
        if image.exists():
            pixmap = QPixmap(str(image))
            if not pixmap.isNull():
                self.preview.setPixmap(pixmap.scaled(
                    self.preview.size(), Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                ))
                return
        self.preview.setText("SKYZEN")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.project_window is not None:
            self.project_window.open_project(self.project_path)
        super().mousePressEvent(event)


class TrashBinDialog(QDialog):
    """Skyzen Recycle Bin-style manager."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.settings = parent.settings if parent else load_settings()
        self.setWindowTitle("Skyzen — Trash Bin")
        self.resize(900, 600)
        self.setMinimumSize(700, 480)
        self.build_ui()
        self.apply_style()
        self.refresh()

    def build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(24,22,24,22); root.setSpacing(16)
        header=QHBoxLayout(); title_box=QVBoxLayout()
        title=QLabel("Trash Bin"); title.setObjectName("TrashTitle")
        subtitle=QLabel("Recover deleted projects or permanently remove them."); subtitle.setObjectName("TrashSubtitle")
        title_box.addWidget(title); title_box.addWidget(subtitle); header.addLayout(title_box,1)
        self.empty_btn=QPushButton("🗑  Empty Bin"); self.empty_btn.setObjectName("DangerButton"); self.empty_btn.setMinimumHeight(40); self.empty_btn.clicked.connect(self.empty_trash); header.addWidget(self.empty_btn); root.addLayout(header)
        controls=QHBoxLayout(); controls.addWidget(QLabel("Automatic deletion after:"))
        self.days_combo=QComboBox(); self.days_combo.addItems(["Never","1 day","3 days","7 days","14 days","30 days","60 days","90 days"])
        current=int(self.settings.get("trash_retention_days",30)); self.days_combo.setCurrentText("Never" if current==0 else f"{current} day"+('' if current==1 else 's'))
        self.days_combo.currentTextChanged.connect(self.retention_changed); controls.addWidget(self.days_combo); controls.addStretch()
        self.info=QLabel(); self.info.setObjectName("TrashInfo"); controls.addWidget(self.info); root.addLayout(controls)
        self.list_widget=QWidget(); self.list_layout=QVBoxLayout(self.list_widget); self.list_layout.setContentsMargins(2,2,2,2); self.list_layout.setSpacing(9)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setWidget(self.list_widget); root.addWidget(scroll,1)
        bottom=QHBoxLayout(); self.cycle_label=QLabel(); self.cycle_label.setObjectName("TrashCycle"); bottom.addWidget(self.cycle_label); bottom.addStretch()
        close_btn=QPushButton("Close"); close_btn.setMinimumWidth(90); close_btn.clicked.connect(self.accept); bottom.addWidget(close_btn); root.addLayout(bottom)

    def retention_changed(self,value):
        days=0 if value=="Never" else int(value.split()[0]); self.settings["trash_retention_days"]=days; save_settings(self.settings); self.purge_expired(); self.refresh()
        if self.parent_window: self.parent_window.settings["trash_retention_days"]=days

    def purge_expired(self):
        days=int(self.settings.get("trash_retention_days",30))
        if days<=0: return
        now=datetime.now()
        for path,deleted_at in self.trash_items():
            if now-deleted_at>=timedelta(days=days):
                try: shutil.rmtree(path)
                except Exception: pass

    def trash_items(self):
        items=[]
        for path in TRASH_DIR.iterdir():
            if not path.is_dir(): continue
            marker=path/".deleted_at"; deleted_at=None
            if marker.exists():
                try: deleted_at=datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
                except Exception: pass
            if deleted_at is None: deleted_at=datetime.fromtimestamp(path.stat().st_mtime)
            items.append((path,deleted_at))
        return sorted(items,key=lambda x:x[1],reverse=True)

    def refresh(self):
        self.purge_expired()
        while self.list_layout.count():
            item=self.list_layout.takeAt(0); widget=item.widget()
            if widget: widget.deleteLater()
        items=self.trash_items(); self.info.setText(f"{len(items)} item{'s' if len(items)!=1 else ''}"); self.empty_btn.setEnabled(bool(items))
        days=int(self.settings.get("trash_retention_days",30)); self.cycle_label.setText("Automatic deletion: Never" if days<=0 else f"Automatic deletion: {days} day{'s' if days!=1 else ''}")
        if not items:
            empty=QLabel("🗑\n\nTrash Bin is empty"); empty.setObjectName("EmptyTrash"); empty.setAlignment(Qt.AlignCenter); self.list_layout.addWidget(empty); self.list_layout.addStretch(); return
        for path,deleted_at in items:
            row=QFrame(); row.setObjectName("TrashRow"); layout=QHBoxLayout(row); layout.setContentsMargins(14,12,14,12)
            icon=QLabel("📁"); icon.setObjectName("TrashIcon"); layout.addWidget(icon)
            box=QVBoxLayout(); name=QLabel(path.name.split("__")[0]); name.setObjectName("TrashName"); deleted=QLabel(f"Deleted: {deleted_at.strftime('%d %b %Y, %I:%M %p')}"); deleted.setObjectName("TrashDate"); box.addWidget(name); box.addWidget(deleted); layout.addLayout(box,1)
            restore=QPushButton("Restore"); restore.clicked.connect(lambda checked=False,p=path:self.restore_item(p)); layout.addWidget(restore)
            delete=QPushButton("Delete Permanently"); delete.setObjectName("DangerButton"); delete.clicked.connect(lambda checked=False,p=path:self.delete_item(p)); layout.addWidget(delete)
            self.list_layout.addWidget(row)
        self.list_layout.addStretch()

    def restore_item(self,path):
        original_name=path.name.split("__")[0]; target=PROJECTS_DIR/original_name
        if target.exists():
            if QMessageBox.question(self,"Project Already Exists",f'"{original_name}" already exists.\n\nRestore with a new name?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            target=PROJECTS_DIR/f"{original_name} (Restored)"; counter=2
            while target.exists(): target=PROJECTS_DIR/f"{original_name} (Restored {counter})"; counter+=1
        try:
            shutil.move(str(path),str(target)); marker=target/".deleted_at"
            if marker.exists(): marker.unlink()
        except Exception as exc: QMessageBox.critical(self,"Restore Failed",str(exc)); return
        self.refresh()
        if self.parent_window: self.parent_window.refresh_projects()

    def delete_item(self,path):
        if QMessageBox.warning(self,"Delete Permanently",f'Permanently delete "{path.name.split("__")[0]}"?\n\nThis action cannot be undone.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        try: shutil.rmtree(path)
        except Exception as exc: QMessageBox.critical(self,"Delete Failed",str(exc)); return
        self.refresh()

    def empty_trash(self):
        items=self.trash_items()
        if not items: return
        if QMessageBox.warning(self,"Empty Trash",f"Permanently delete all {len(items)} item(s)?\n\nThis action cannot be undone.",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        for path,_ in items:
            try: shutil.rmtree(path)
            except Exception: pass
        self.refresh()

    def apply_style(self): self.setStyleSheet(build_stylesheet(self.settings))


class ProjectWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("Skyzen — Projects")
        self.resize(1100, 720)
        self.setMinimumSize(800, 520)

        self.editor_window = None
        self.build_ui()
        self.apply_theme()

    def build_ui(self):
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(18)

        top = QHBoxLayout()
        title = QLabel("Skyzen")
        title.setObjectName("Title")

        subtitle = QLabel("Projects")
        subtitle.setObjectName("Subtitle")

        top_left = QVBoxLayout()
        top_left.setSpacing(2)
        top_left.addWidget(title)
        top_left.addWidget(subtitle)

        top.addLayout(top_left)
        top.addStretch()

        self.trash_btn = QPushButton("🗑  Trash Bin")
        self.trash_btn.setObjectName("TopButton")
        self.trash_btn.clicked.connect(self.open_trash)
        top.addWidget(self.trash_btn)

        self.settings_btn = QPushButton("⚙  Settings")
        self.settings_btn.setObjectName("TopButton")
        self.settings_btn.clicked.connect(self.open_settings)
        top.addWidget(self.settings_btn)

        root.addLayout(top)

        self.new_btn = QPushButton("＋  Create New Project")
        self.new_btn.setObjectName("NewProject")
        self.new_btn.setMinimumHeight(64)
        self.new_btn.clicked.connect(self.create_project)
        root.addWidget(self.new_btn)

        projects_title = QLabel("Your Projects")
        projects_title.setObjectName("SectionTitle")
        root.addWidget(projects_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        # 20 px gap on all four edges, 18 px between cards in both directions
        self.grid.setContentsMargins(20, 20, 20, 20)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        scroll.setWidget(self.container)
        root.addWidget(scroll, 1)

        self.refresh_projects()

    def project_dirs(self):
        # Stable, serial-friendly order: oldest project first, then name for ties.
        # Missing/invalid metadata safely falls back to folder creation time/name.
        def sort_key(path):
            created = ""
            metadata_file = path / "project.json"
            if metadata_file.exists():
                try:
                    created = str(json.loads(metadata_file.read_text(encoding="utf-8")).get("created", ""))
                except Exception:
                    pass
            return (created or datetime.fromtimestamp(path.stat().st_ctime).isoformat(), path.name.casefold())
        return sorted([p for p in PROJECTS_DIR.iterdir() if p.is_dir()], key=sort_key)

    def refresh_projects(self):
        # Clear all items including any stretch spacers added previously
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        # Reset all column stretches from the previous layout
        for col in range(self.grid.columnCount() + 1):
            self.grid.setColumnStretch(col, 0)

        projects = self.project_dirs()
        # Account for edge margins (left + right = 40) and scroll-bar (~20) in column count
        h_spacing = self.grid.horizontalSpacing()
        card_w = 160
        available = max(card_w, self.centralWidget().width() - 40 - 20)
        columns = max(1, min(8, (available + h_spacing) // (card_w + h_spacing)))

        for index, path in enumerate(projects, start=1):
            card = ProjectCard(path, index, self.container, self)
            card.menu_requested.connect(self.project_menu)
            row = (index - 1) // columns
            col = (index - 1) % columns
            # AlignTop keeps cards pinned to the top of each cell;
            # no horizontal alignment flag lets the cell size drive card placement.
            self.grid.addWidget(card, row, col, Qt.AlignTop)

        # Trailing stretch column so cards cluster left instead of spreading out
        self.grid.setColumnStretch(columns, 1)
        # Trailing stretch row so cards cluster top instead of spreading down
        total_rows = max(1, (len(projects) + columns - 1) // columns)
        self.grid.setRowStretch(total_rows, 1)
        self.refresh_trash_button()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "grid"):
            self.refresh_projects()

    def create_project(self):
        name, ok = QInputDialog.getText(self, "Create New Project", "Project name:")
        if not ok:
            return

        name = name.strip()
        if not name:
            return

        safe = "".join(c for c in name if c not in '<>:"/\\|?*').strip()
        if not safe:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid project name.")
            return

        path = PROJECTS_DIR / safe
        if path.exists():
            QMessageBox.warning(self, "Project Exists", "A project with this name already exists.")
            return

        path.mkdir(parents=True)
        metadata = {
            "name": safe,
            "created": datetime.now().isoformat(timespec="seconds"),
            "modified": datetime.now().isoformat(timespec="seconds"),
            "version": 1,
        }
        (path / "project.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        self.refresh_projects()
        self.open_project(path)

    def project_menu(self, card):
        menu = QMenu(self)
        open_action = menu.addAction("Open Project")
        duplicate_action = menu.addAction("Duplicate Project")
        rename_action = menu.addAction("Rename Project")
        menu.addSeparator()
        trash_action = menu.addAction("Move to Trash")
        action = menu.exec(card.dots.mapToGlobal(card.dots.rect().bottomLeft()))

        if action == open_action:
            self.open_project(card.project_path)
        elif action == duplicate_action:
            self.duplicate_project(card.project_path)
        elif action == rename_action:
            self.rename_project(card.project_path)
        elif action == trash_action:
            self.move_to_trash(card.project_path)

    def duplicate_project(self, source):
        """Create an independent copy of a project folder and its saved state."""
        base_name = f"{source.name} (Copy)"
        target = PROJECTS_DIR / base_name
        suffix = 2
        while target.exists():
            target = PROJECTS_DIR / f"{source.name} (Copy {suffix})"
            suffix += 1
        try:
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".deleted_at", "__pycache__", "*.pyc"))
            metadata_file = target / "project.json"
            metadata = {}
            if metadata_file.exists():
                try:
                    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                except Exception:
                    metadata = {}
            now = datetime.now().isoformat(timespec="seconds")
            metadata.update({"name": target.name, "created": now, "modified": now, "version": metadata.get("version", 1)})
            metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        except Exception as exc:
            try:
                if target.exists():
                    shutil.rmtree(target)
            except Exception:
                pass
            QMessageBox.critical(self, "Duplicate Failed", f"Could not duplicate this project.\n\n{exc}")
            return
        self.refresh_projects()

    def open_project(self, path):
        """Open the selected project in the full editor and return here on close."""
        # Guard: don't open a second editor while one is already running.
        if self.editor_window is not None:
            try:
                self.editor_window.raise_()
                self.editor_window.activateWindow()
                return
            except RuntimeError:
                self.editor_window = None

        try:
            from app.main_window.main import EditorMainWindow
            editor = EditorMainWindow(root_dir=Path(path).resolve())
            editor.setWindowTitle(f"Skyzen — {Path(path).name}")

            # Use the proper Qt signal (defined on EditorMainWindow) so the
            # callback fires reliably through Qt's C++ dispatch path.
            # Python monkey-patching of closeEvent is silently ignored by Qt.
            editor.editor_closed.connect(self._editor_closed)

            self.editor_window = editor
            self.hide()
            editor.show()
            editor.raise_()
            editor.activateWindow()
        except Exception as exc:
            self.editor_window = None
            QMessageBox.critical(
                self, "Could Not Open Project",
                f"Skyzen could not open this project.\n\n{exc}"
            )
            self.show()

    def _editor_closed(self):
        self.editor_window = None
        self.refresh_projects()
        self.show()
        self.raise_()
        self.activateWindow()

    def rename_project(self, path):
        new_name, ok = QInputDialog.getText(
            self, "Rename Project", "New project name:", text=path.name
        )
        if not ok:
            return

        new_name = "".join(
            c for c in new_name.strip() if c not in '<>:"/\\|?*'
        ).strip()
        if not new_name or new_name == path.name:
            return

        target = PROJECTS_DIR / new_name
        if target.exists():
            QMessageBox.warning(self, "Project Exists", "That project already exists.")
            return

        path.rename(target)
        metadata_file = target / "project.json"
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                metadata["name"] = new_name
                metadata["modified"] = datetime.now().isoformat(timespec="seconds")
                metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            except Exception:
                pass
        self.refresh_projects()

    def move_to_trash(self, path):
        answer = QMessageBox.question(
            self,
            "Move to Trash",
            f'Move "{path.name}" to the Skyzen Trash?\n\n'
            "It can be permanently deleted later.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = TRASH_DIR / f"{path.name}__{stamp}"
        shutil.move(str(path), str(target))
        (target / ".deleted_at").write_text(
            datetime.now().isoformat(timespec="seconds"), encoding="utf-8"
        )
        self.refresh_projects()

    def open_trash(self):
        dialog = TrashBinDialog(self)
        dialog.exec()
        self.refresh_projects()

    def refresh_trash_button(self):
        count = len([p for p in TRASH_DIR.iterdir() if p.is_dir()])
        self.trash_btn.setText(
            f"🗑  Trash Bin  ({count})" if count else "🗑  Trash Bin"
        )

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = dialog.get_settings()
            save_settings(self.settings)
            self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(build_stylesheet(self.settings))

    def closeEvent(self, event):
        """Closing the project window exits the application."""
        super().closeEvent(event)
        if event.isAccepted():
            QApplication.instance().quit()


def build_stylesheet(settings):
    bg = settings.get("background", "#101116")
    panel = settings.get("panel", "#171922")
    text = settings.get("text", "#F3F5F7")
    muted = settings.get("muted", "#969CAB")
    accent = settings.get("accent", "#8B5CF6")
    hover = settings.get("hover", "#A78BFA")
    border = settings.get("border", "#2B2E3A")

    return f"""
    QWidget#Root {{
        background: {bg};
        color: {text};
        font-family: "Segoe UI";
    }}
    QLabel#Title {{
        color: {text};
        font-size: 28px;
        font-weight: 700;
    }}
    QLabel#Subtitle {{
        color: {muted};
        font-size: 14px;
    }}
    QLabel#SectionTitle {{
        color: {text};
        font-size: 18px;
        font-weight: 650;
    }}
    QPushButton {{
        background: {panel};
        color: {text};
        border: 1px solid {border};
        border-radius: 9px;
        padding: 8px 14px;
    }}
    QPushButton:hover {{
        border: 1px solid {hover};
        background: {panel};
    }}
    QPushButton:pressed {{
        border: 1px solid {accent};
    }}
    QPushButton#TopButton {{
        min-width: 118px;
        min-height: 38px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton#NewProject {{
        background: {panel};
        border: 1px solid {accent};
        border-radius: 12px;
        font-size: 16px;
        font-weight: 650;
    }}
    QPushButton#NewProject:hover {{
        border: 2px solid {hover};
        background: {accent};
    }}
    QFrame#ProjectCard {{
        background: {panel};
        border: 1px solid {border};
        border-radius: 12px;
    }}
    QFrame#ProjectCard:hover {{
        border: 2px solid {hover};
    }}
    QLabel#ProjectPreview {{
        background: {bg};
        border: 1px solid {border};
        border-radius: 8px;
        color: {muted};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel#ProjectName {{
        color: {text};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#ProjectSerial {{
        color: {muted};
        font-size: 10px;
        font-weight: 700;
        background: {bg};
        border: 1px solid {border};
        border-radius: 5px;
        padding: 2px;
    }}
    QPushButton#ProjectDots {{
        border: 1px solid {border};
        border-radius: 7px;
        padding: 0;
        font-size: 20px;
    }}
    QPushButton#ProjectDots:hover {{
        border: 1px solid {hover};
        color: {hover};
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QLabel#TrashTitle {{
        font-size: 25px;
        font-weight: 700;
        color: {text};
    }}
    QLabel#TrashSubtitle, QLabel#TrashDate {{
        color: {muted};
    }}
    QLabel#TrashInfo {{
        color: {text};
        font-size: 14px;
        font-weight: 600;
    }}
    QLabel#TrashCycle {{
        color: {muted};
    }}
    QLabel#EmptyTrash {{
        color: {muted};
        font-size: 18px;
        padding: 60px;
    }}
    QFrame#TrashRow {{
        background: {panel};
        border: 1px solid {border};
        border-radius: 10px;
    }}
    QFrame#TrashRow:hover {{
        border: 2px solid {hover};
    }}
    QLabel#TrashName {{
        color: {text};
        font-size: 15px;
        font-weight: 600;
    }}
    QPushButton#DangerButton {{
        border: 1px solid #7A3340;
    }}
    QPushButton#DangerButton:hover {{
        border: 2px solid #E05A70;
        background: #351820;
    }}
    QMenu {{
        background: {panel};
        color: {text};
        border: 1px solid {border};
        padding: 5px;
    }}
    QMenu::item {{
        padding: 8px 24px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background: {accent};
    }}
    QLabel#TrashTitle {{ font-size: 25px; font-weight: 700; color: {text}; }}
    QLabel#TrashSubtitle, QLabel#TrashDate {{ color: {muted}; }}
    QLabel#TrashInfo {{ color: {text}; font-size: 14px; font-weight: 600; }}
    QLabel#TrashCycle {{ color: {muted}; }}
    QLabel#EmptyTrash {{ color: {muted}; font-size: 18px; padding: 60px; }}
    QFrame#TrashRow {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
    QFrame#TrashRow:hover {{ border: 2px solid {hover}; }}
    QLabel#TrashName {{ color: {text}; font-size: 15px; font-weight: 600; }}
    QPushButton#DangerButton {{ border: 1px solid #7A3340; }}
    QPushButton#DangerButton:hover {{ border: 2px solid #E05A70; background: #351820; }}
    QPushButton#TrashButton {{
        background: {panel};
        color: {text};
        border: 1px solid {border};
        border-radius: 10px;
        font-size: 14px;
        font-weight: 600;
    }}
    QPushButton#TrashButton:hover {{
        border: 2px solid {hover};
        background: {panel};
    }}
    """


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Skyzen")
    window = ProjectWindow()
    window.show()
    sys.exit(app.exec())
