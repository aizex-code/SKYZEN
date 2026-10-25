"""Export setup and dedicated live-progress panel for Skyzen."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from PySide6.QtCore import Qt, QSettings, QUrl, QTimer, QPoint
from PySide6.QtGui import QDesktopServices, QPixmap, QIcon, QPainter, QColor, QLinearGradient, QPolygon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QSlider, QDoubleSpinBox,
)

from .codec_profiles import PROFILES, RESOLUTIONS, export_options
from .export_worker import ExportWorker
from app.video_engine.project_snapshot import build_snapshot
from app.video_engine.ffmpeg_backend import build_frame_command, find_binary


class AnimatedGradientProgressBar(QProgressBar):
    """A lightweight native Qt progress bar with a moving violet/pink sheen.

    The filled length still follows FFmpeg's real progress; the animation only
    moves the gradient inside that filled region (no fake progress or Turtle window).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0
        self.setRange(0, 100)
        self.setValue(0)
        self.setFormat("%p%")
        self.setMinimumHeight(22)
        self.setMaximumHeight(22)
        self._animation = QTimer(self)
        self._animation.setInterval(35)
        self._animation.timeout.connect(self._advance_gradient)
        self._animation.start()

    def _advance_gradient(self):
        self._phase = (self._phase + 5) % 240
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 1, 0, -1)
        radius = min(8.0, rect.height() / 2.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#20202C"))
        painter.drawRoundedRect(rect, radius, radius)
        progress = max(0.0, min(1.0, self.value() / 100.0))
        fill_width = int(rect.width() * progress)
        if fill_width > 0:
            fill_rect = rect.adjusted(0, 0, -(rect.width() - fill_width), 0)
            gradient = QLinearGradient(fill_rect.left() - self._phase, 0,
                                       fill_rect.left() + max(1, fill_rect.width()), 0)
            gradient.setColorAt(0.0, QColor("#8B5CF6"))
            gradient.setColorAt(0.48, QColor("#D946EF"))
            gradient.setColorAt(0.76, QColor("#EC4899"))
            gradient.setColorAt(1.0, QColor("#A855F7"))
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill_rect, radius, radius)
            # A narrow moving highlight gives the filled area a subtle animated sheen.
            highlight_x = fill_rect.left() + (self._phase % max(1, fill_rect.width()))
            highlight = QLinearGradient(highlight_x - 16, 0, highlight_x + 16, 0)
            highlight.setColorAt(0.0, QColor(255, 255, 255, 0))
            highlight.setColorAt(0.5, QColor(255, 255, 255, 65))
            highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(highlight)
            painter.drawRoundedRect(fill_rect, radius, radius)
        painter.setPen(QColor("#FFFFFF"))
        display_text = f"{self.value()}%" if self.format() == "%p%" else self.format()
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), display_text)
        painter.end()


def _youtube_icon():
    """Return a small locally-drawn YouTube-style play icon (no network assets)."""
    pixmap = QPixmap(26, 19)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F04468"))
    painter.drawRoundedRect(0, 1, 25, 17, 5, 5)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawPolygon(QPolygon([QPoint(10, 5), QPoint(10, 14), QPoint(17, 9)]))
    painter.end()
    return QIcon(pixmap)


class ProjectFramePicker(QDialog):
    """Let users scrub the composed project timeline and explicitly choose a thumbnail frame."""
    def __init__(self, parent, root_dir, snapshot, initial_time=0.0):
        super().__init__(parent)
        self.root_dir = Path(root_dir)
        self.snapshot = snapshot
        self.duration = max(0.0, float(snapshot.get("duration", 0.0)))
        self._time = max(0.0, min(float(initial_time or 0.0), max(0.0, self.duration)))
        self._preview_file = ""
        self.setWindowTitle("Select Project Thumbnail Frame")
        self.setMinimumSize(480, 380)
        self.resize(520, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)
        self.preview = QLabel("Choose a time, then click Preview frame")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(440, 248)
        self.preview.setStyleSheet("background:#080B10;border:1px solid #303A47;border-radius:5px;color:#8492A6;")
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.time_label = QLabel("Time")
        self.time_spin = QDoubleSpinBox(); self.time_spin.setRange(0.0, self.duration); self.time_spin.setDecimals(3); self.time_spin.setSuffix(" s"); self.time_spin.setValue(self._time)
        self.time_slider = QSlider(Qt.Orientation.Horizontal); self.time_slider.setRange(0, max(1, int(self.duration * 1000))); self.time_slider.setValue(int(self._time * 1000))
        row.addWidget(self.time_label); row.addWidget(self.time_slider, 1); row.addWidget(self.time_spin)
        layout.addLayout(row)
        note = QLabel("Scrub to the exact moment you want. Preview shows the composed project frame, including visible effects and adjustments.")
        note.setWordWrap(True); note.setStyleSheet("color:#91A0B3;font-size:11px;")
        layout.addWidget(note)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        self.preview_button = QPushButton("Preview frame")
        self.cancel_button = QPushButton("Cancel")
        self.use_button = QPushButton("Use this frame")
        self.use_button.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #8B5CF6,stop:1 #EC4899);color:#FFFFFF;font-weight:800;border:0;")
        buttons.addWidget(self.preview_button); buttons.addWidget(self.cancel_button); buttons.addWidget(self.use_button)
        layout.addLayout(buttons)
        self.time_slider.valueChanged.connect(self._slider_changed)
        self.time_spin.valueChanged.connect(self._spin_changed)
        self.preview_button.clicked.connect(self._render_preview)
        self.cancel_button.clicked.connect(self.reject)
        self.use_button.clicked.connect(self.accept)
        self._render_preview()

    def _slider_changed(self, value):
        self._time = value / 1000.0
        self.time_spin.blockSignals(True); self.time_spin.setValue(self._time); self.time_spin.blockSignals(False)

    def _spin_changed(self, value):
        self._time = float(value)
        self.time_slider.blockSignals(True); self.time_slider.setValue(int(self._time * 1000)); self.time_slider.blockSignals(False)

    def selected_time(self):
        return max(0.0, min(self._time, self.duration))

    def _render_preview(self):
        ffmpeg = find_binary(self.root_dir, "ffmpeg.exe") or find_binary(self.root_dir, "ffmpeg")
        if not ffmpeg:
            self.preview.setText("FFmpeg was not found. Add FFmpeg to the project before previewing a project frame.")
            return
        try:
            fd, output = tempfile.mkstemp(prefix="skyzen_thumb_preview_", suffix=".jpg")
            import os
            os.close(fd)
            self._preview_file = output
            command = build_frame_command(ffmpeg, self.snapshot, self.selected_time(), output)
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, timeout=20, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            pixmap = QPixmap(output)
            if result.returncode != 0 or pixmap.isNull():
                self.preview.setText("No visible project frame at this time. Move to a time containing video or image media, then preview again.")
                return
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except (OSError, subprocess.SubprocessError, Exception) as exc:
            self.preview.setText(f"Could not preview this frame: {exc}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._preview_file and Path(self._preview_file).is_file():
            pixmap = QPixmap(self._preview_file)
            if not pixmap.isNull():
                self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def closeEvent(self, event):
        try:
            if self._preview_file:
                Path(self._preview_file).unlink(missing_ok=True)
        except OSError:
            pass
        super().closeEvent(event)


class ExportDialog(QDialog):
    def __init__(self, timeline, root_dir, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.root_dir = Path(root_dir)
        self.settings = QSettings("Skyzen", "Editor")
        self.worker = None
        self.output_path = ""
        self._success_path = ""
        self._thumbnail_path = ""
        self._custom_thumbnail = ""
        self._snapshot = None
        self._thumbnail_time = max(0.0, float(getattr(timeline, "playhead", 0.0)))
        default_dir = Path.home() / "Videos" / "Skyzen Exports"
        stored_dir = str(self.settings.value("export/output_dir", str(default_dir)))
        self.output_dir = Path(stored_dir).expanduser()
        self.setWindowTitle("Export Project — Skyzen Editor")
        self.setMinimumSize(700, 570)
        self.resize(740, 630)
        self.setMaximumWidth(820)
        self.setStyleSheet("""
            QDialog { background:#0D0D15; color:#F3EEF9; }
            QLabel { color:#E5DDF0; }
            QComboBox,QSpinBox,QLineEdit,QPushButton {
                background:#171521; color:#F3EEF9; border:1px solid #383047;
                border-radius:7px; padding:7px 9px;
            }
            QComboBox:hover,QSpinBox:hover,QLineEdit:hover,QPushButton:hover { border-color:#D946EF; }
            QProgressBar { background:#20202C; border:1px solid #383047; border-radius:8px; height:22px; text-align:center; color:#FFFFFF; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(14)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_settings_page())
        self.pages.addWidget(self._build_progress_page())
        self._load_saved_settings()
        self._update_quality(self.profile.currentText(), reset_value=False)
        self._fps_mode_changed(self.fps_mode.currentText())
        self._thumbnail_mode_changed(self.thumbnail_mode.currentText())

    def _build_settings_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        content = QWidget()
        content.setMaximumWidth(620)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        title = QLabel("EXPORT PROJECT")
        title.setStyleSheet("color:#D8A2FF;font-weight:850;font-size:16px;letter-spacing:1.2px;padding:2px 0 5px 0;")
        root.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(11)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.project_name = QLineEdit("Skyzen_Project")
        self.project_name.setPlaceholderText("Project / export name")
        self.profile = QComboBox(); self.profile.addItems(PROFILES.keys())
        self.resolution = QComboBox(); self.resolution.addItems(RESOLUTIONS.keys())
        self.fps_mode = QComboBox(); self.fps_mode.addItems(["Best for project (recommended)", "24 FPS", "25 FPS", "30 FPS", "48 FPS", "50 FPS", "60 FPS", "Custom…"])
        self.fps = QSpinBox(); self.fps.setRange(1, 60); self.fps.setValue(30); self.fps.setSuffix(" FPS")
        self.fps_row = QWidget(); fps_layout = QHBoxLayout(self.fps_row)
        fps_layout.setContentsMargins(0, 0, 0, 0); fps_layout.setSpacing(8)
        fps_layout.addWidget(self.fps_mode, 1); fps_layout.addWidget(self.fps, 0)
        self.speed_preset = QComboBox(); self.speed_preset.addItems([
            "Best balance (recommended)", "Faster export", "Balanced", "Higher quality"
        ])
        self.quality = QSpinBox(); self.quality.setToolTip("Lower CRF usually means higher quality and larger files.")
        self.thumbnail_mode = QComboBox(); self.thumbnail_mode.addItems(["None", "Current project frame", "Custom image"])
        self.thumbnail_button = QPushButton("Choose image…")
        self.thumbnail_row = QWidget(); thumbnail_layout = QHBoxLayout(self.thumbnail_row)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0); thumbnail_layout.setSpacing(8)
        thumbnail_layout.addWidget(self.thumbnail_mode, 1); thumbnail_layout.addWidget(self.thumbnail_button, 0)
        self.thumbnail_note = QLabel("Optional: saves a separate thumbnail image beside the exported video.")
        self.thumbnail_note.setWordWrap(True); self.thumbnail_note.setStyleSheet("color:#8492A6;font-size:11px;")

        self.output_dir_edit = QLineEdit(str(self.output_dir))
        self.output_dir_edit.setReadOnly(True)
        self.output_dir_button = QPushButton("Choose folder…")
        folder_row = QWidget(); folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0); folder_layout.setSpacing(8)
        folder_layout.addWidget(self.output_dir_edit, 1); folder_layout.addWidget(self.output_dir_button)

        for widget in (self.project_name, self.profile, self.resolution, self.fps_row,
                       self.speed_preset, self.quality, self.thumbnail_row, folder_row):
            widget.setMaximumWidth(620)
        self.fps.setEnabled(False)
        self.fps.setMaximumWidth(125)
        self.thumbnail_button.setMinimumWidth(125)
        self.thumbnail_button.setMaximumWidth(165)
        form.addRow("Project / export name", self.project_name)
        form.addRow("Codec / container", self.profile)
        form.addRow("Resolution", self.resolution)
        form.addRow("Frame rate", self.fps_row)
        form.addRow("Encoding speed", self.speed_preset)
        form.addRow("Quality (CRF)", self.quality)
        form.addRow("Thumbnail", self.thumbnail_row)
        form.addRow("Output folder", folder_row)
        root.addLayout(form)
        root.addWidget(self.thumbnail_note)
        info = QLabel("4K UHD supports up to 60 FPS. Higher resolutions and frame rates require more processing power and disk space. Thumbnail images are saved as a separate file alongside the video.")
        info.setWordWrap(True)
        info.setStyleSheet("background:#1B2028;padding:10px;border-radius:5px;color:#9BA9BA;")
        root.addWidget(info)
        root.addStretch(1)

        buttons = QHBoxLayout()
        self.save_settings_button = QPushButton("Save settings")
        self.cancel_button = QPushButton("Cancel")
        self.export_button = QPushButton("Export…")
        self.export_button.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #8B5CF6,stop:1 #EC4899);color:#FFFFFF;font-weight:800;border:0;padding:8px 16px;} QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #A78BFA,stop:1 #F472B6);}")
        buttons.addWidget(self.save_settings_button)
        buttons.addStretch(1); buttons.addWidget(self.cancel_button); buttons.addWidget(self.export_button)
        root.addLayout(buttons)
        page_layout.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)
        page_layout.addStretch(1)

        self.cancel_button.clicked.connect(self.reject)
        self.export_button.clicked.connect(self._choose_output)
        self.save_settings_button.clicked.connect(self._save_settings)
        self.profile.currentTextChanged.connect(self._update_quality)
        self.fps_mode.currentTextChanged.connect(self._fps_mode_changed)
        self.thumbnail_mode.currentTextChanged.connect(self._thumbnail_mode_changed)
        self.thumbnail_button.clicked.connect(self._choose_thumbnail)
        self.output_dir_button.clicked.connect(self._choose_output_folder)
        return page

    def _build_progress_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setMaximumWidth(650)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(16)

        title = QLabel("SKYZEN EXPORT")
        title.setStyleSheet("color:#D8A2FF;font-weight:900;font-size:20px;letter-spacing:1.5px;padding-bottom:2px;")
        root.addWidget(title)

        self.progress_status = QLabel("Preparing export…")
        self.progress_status.setWordWrap(True)
        self.progress_status.setStyleSheet("font-size:13px;color:#F2EAF8;padding:2px 0;")
        root.addWidget(self.progress_status)

        self.progress_bar = AnimatedGradientProgressBar()
        root.addWidget(self.progress_bar)

        self.progress_details = QLabel("Elapsed: 00:00:00")
        self.progress_details.setStyleSheet("color:#AFA3BF;font-size:11px;padding-top:1px;")
        root.addWidget(self.progress_details)

        self.output_label = QLabel("")
        self.output_label.setWordWrap(True)
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.output_label.setStyleSheet("color:#C7BED5;background:#171521;border:1px solid #30283B;padding:12px;border-radius:8px;line-height:1.35;")
        root.addWidget(self.output_label)

        support = QWidget()
        support.setStyleSheet("QWidget#supportCard{background:#171521;border:1px solid #40304F;border-radius:10px;}")
        support.setObjectName("supportCard")
        support_layout = QVBoxLayout(support)
        support_layout.setContentsMargins(14, 13, 14, 14)
        support_layout.setSpacing(10)
        support_title = QLabel("SUPPORT THE CREATORS")
        support_title.setStyleSheet("color:#E879F9;font-weight:850;font-size:12px;letter-spacing:.6px;border:0;background:transparent;")
        support_layout.addWidget(support_title)
        support_text = QLabel("Skyzen is built for creators. If you enjoy it, support our music and creative work on these channels:")
        support_text.setWordWrap(True)
        support_text.setStyleSheet("color:#C5BBD2;border:0;background:transparent;")
        support_layout.addWidget(support_text)

        channels = QHBoxLayout()
        channels.setSpacing(10)
        self.bronveil_button = QPushButton("BRONVEIL  ·  @bronveil")
        self.bronveil_button.setIcon(_youtube_icon())
        self.bronveil_button.setIconSize(QPixmap(26, 19).size())
        self.bronveil_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bronveil_button.setToolTip("Open the BRONVEIL YouTube channel")
        self.bronveil_button.setStyleSheet("QPushButton{background:#21172B;border:1px solid #6D3B87;color:#F5D9FF;text-align:left;padding:9px 12px;font-weight:700;} QPushButton:hover{background:#30203E;border-color:#D946EF;}")
        self.s7xian_button = QPushButton("S7XIAN  ·  @s7xian")
        self.s7xian_button.setIcon(_youtube_icon())
        self.s7xian_button.setIconSize(QPixmap(26, 19).size())
        self.s7xian_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.s7xian_button.setToolTip("Open the S7XIAN YouTube channel")
        self.s7xian_button.setStyleSheet("QPushButton{background:#21172B;border:1px solid #6D3B87;color:#F5D9FF;text-align:left;padding:9px 12px;font-weight:700;} QPushButton:hover{background:#30203E;border-color:#EC4899;}")
        channels.addWidget(self.bronveil_button, 1)
        channels.addWidget(self.s7xian_button, 1)
        support_layout.addLayout(channels)
        root.addWidget(support)
        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.open_output_button = QPushButton("Open output folder")
        self.progress_close_button = QPushButton("Done")
        self.progress_close_button.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #8B5CF6,stop:1 #EC4899);color:#FFFFFF;font-weight:800;border:0;padding:8px 16px;} QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #A78BFA,stop:1 #F472B6);}")
        buttons.addWidget(self.open_output_button)
        buttons.addWidget(self.progress_close_button)
        root.addLayout(buttons)

        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.open_output_button.clicked.connect(self._open_output_folder)
        self.progress_close_button.clicked.connect(self._close_progress)
        self.bronveil_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.youtube.com/@bronveil")))
        self.s7xian_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.youtube.com/@s7xian")))
        return page

    def _load_saved_settings(self):
        s = self.settings
        self.project_name.setText(str(s.value("export/project_name", "Skyzen_Project")))
        self.profile.setCurrentText(str(s.value("export/profile", "H.264 (MP4)")))
        self.resolution.setCurrentText(str(s.value("export/resolution", "1080p (Full HD)")))
        self.fps_mode.setCurrentText(str(s.value("export/fps_mode", "Best for project (recommended)")))
        self.fps.setValue(max(1, min(60, int(s.value("export/custom_fps", 30)))))
        self.speed_preset.setCurrentText(str(s.value("export/speed_preset", "Best balance (recommended)")))
        self.thumbnail_mode.setCurrentText(str(s.value("export/thumbnail_mode", "None")))
        self._custom_thumbnail = str(s.value("export/custom_thumbnail", ""))
        try:
            self._thumbnail_time = max(0.0, float(s.value("export/thumbnail_time", self._thumbnail_time)))
        except (TypeError, ValueError):
            pass
        if self._custom_thumbnail and Path(self._custom_thumbnail).is_file():
            self.thumbnail_button.setText(Path(self._custom_thumbnail).name)
        self.quality.setValue(int(s.value("export/quality", 20)))
        if self.output_dir.exists() and self.output_dir.is_dir():
            self.output_dir_edit.setText(str(self.output_dir))
        else:
            self.output_dir = Path.home() / "Videos" / "Skyzen Exports"
            self.output_dir_edit.setText(str(self.output_dir))

    def _save_settings(self):
        s = self.settings
        for key, value in {
            "export/project_name": self.project_name.text().strip() or "Skyzen_Project",
            "export/profile": self.profile.currentText(),
            "export/resolution": self.resolution.currentText(),
            "export/fps_mode": self.fps_mode.currentText(),
            "export/custom_fps": self.fps.value(),
            "export/speed_preset": self.speed_preset.currentText(),
            "export/quality": self.quality.value(),
            "export/thumbnail_mode": self.thumbnail_mode.currentText(),
            "export/custom_thumbnail": self._custom_thumbnail,
            "export/thumbnail_time": self._thumbnail_time,
            "export/output_dir": str(self.output_dir),
        }.items():
            s.setValue(key, value)
        s.sync()
        self.progress_status.setText("Export settings and output folder saved for next time.")
        QMessageBox.information(self, "Settings saved", "Your export settings and output folder will be remembered next time.")

    def _update_quality(self, profile_name, reset_value=True):
        profile = PROFILES.get(profile_name, PROFILES["H.264 (MP4)"])
        low, high = profile["quality_range"]
        self.quality.setRange(low, max(low, high))
        if reset_value:
            self.quality.setValue(profile["quality_default"])
        else:
            self.quality.setValue(max(low, min(high, self.quality.value())))
        self.quality.setEnabled(high > low)
        self.quality.setToolTip("Lower CRF is generally higher quality and larger." if high > low else "This codec uses a fixed quality profile.")

    def _fps_mode_changed(self, mode):
        custom = mode == "Custom…"
        self.fps.setEnabled(custom)
        self.fps.setVisible(custom)

    def _effective_fps(self, snapshot):
        mode = self.fps_mode.currentText()
        if mode == "Custom…":
            return self.fps.value()
        if mode == "Best for project (recommended)":
            value = snapshot.get("fps", getattr(self.timeline, "fps", 30))
            try:
                return max(1, min(60, int(value)))
            except (TypeError, ValueError):
                return 30
        try:
            return max(1, min(60, int(mode.split()[0])))
        except (ValueError, IndexError):
            return 30

    def _thumbnail_mode_changed(self, mode):
        if mode == "Custom image":
            self.thumbnail_button.setVisible(True)
            self.thumbnail_button.setEnabled(True)
            self.thumbnail_button.setText(Path(self._custom_thumbnail).name if self._custom_thumbnail and Path(self._custom_thumbnail).is_file() else "Choose image…")
        elif mode == "Current project frame":
            self.thumbnail_button.setVisible(True)
            self.thumbnail_button.setEnabled(True)
            self.thumbnail_button.setText("Select frame…" if self._thumbnail_time is not None else "Select frame…")
        else:
            self.thumbnail_button.setVisible(False)
            self.thumbnail_button.setEnabled(False)

    def _choose_thumbnail(self):
        mode = self.thumbnail_mode.currentText()
        if mode == "Current project frame":
            snapshot = build_snapshot(self.timeline)
            if not snapshot.get("visual"):
                QMessageBox.information(self, "No project frames", "Add a video or image clip to the timeline before selecting a project-frame thumbnail.")
                return
            dialog = ProjectFramePicker(self, self.root_dir, snapshot, self._thumbnail_time)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._thumbnail_time = dialog.selected_time()
                self.thumbnail_button.setText(f"Frame {self._thumbnail_time:.2f}s")
            return
        start = str(Path(self._custom_thumbnail).parent) if self._custom_thumbnail else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Choose thumbnail image", start, "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._custom_thumbnail = path
            self.thumbnail_button.setText(Path(path).name)

    def _choose_output_folder(self):
        start = str(self.output_dir) if self.output_dir.exists() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose export output folder", start)
        if folder:
            self.output_dir = Path(folder)
            self.output_dir_edit.setText(folder)

    def _choose_output(self):
        snapshot = build_snapshot(self.timeline)
        if not snapshot["clips"]:
            QMessageBox.information(self, "Nothing to export", "Add media to the timeline first.")
            return
        name = self.project_name.text().strip() or "Skyzen_Project"
        safe_name = "".join(c for c in name if c not in '<>:\\"/|?*').strip().rstrip(".") or "Skyzen_Project"
        profile = PROFILES[self.profile.currentText()]
        extension = profile["extension"]
        self.output_dir = Path(self.output_dir_edit.text()).expanduser()
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Output folder unavailable", f"Cannot create the selected output folder:\n{exc}")
            return
        default = str(self.output_dir / f"{safe_name}{extension}")
        filters = {".mp4": "MP4 Video (*.mp4)", ".mov": "QuickTime MOV (*.mov)", ".webm": "WebM Video (*.webm)"}
        path, _ = QFileDialog.getSaveFileName(self, "Export Skyzen Project", default, filters.get(extension, "Video files (*.*)"))
        if not path:
            return
        output = Path(path)
        if output.suffix.lower() != extension:
            output = output.with_suffix(extension)
        try:
            resolved = output.resolve()
            sources = {Path(clip["path"]).resolve() for clip in snapshot["clips"]}
            if resolved in sources:
                QMessageBox.critical(self, "Unsafe export path", "Choose a different output path. Skyzen will never overwrite an original source file.")
                return
        except (OSError, RuntimeError):
            pass
        if self.thumbnail_mode.currentText() == "Custom image" and (not self._custom_thumbnail or not Path(self._custom_thumbnail).is_file()):
            QMessageBox.information(self, "Choose thumbnail", "Choose an existing custom image or select another thumbnail option.")
            return

        width, height = RESOLUTIONS[self.resolution.currentText()]
        fps = self._effective_fps(snapshot)
        speed_map = {
            "Best balance (recommended)": "balanced",
            "Faster export": "fast",
            "Balanced": "balanced",
            "Higher quality": "quality",
        }
        options = export_options(self.profile.currentText(), self.quality.value(), speed_map[self.speed_preset.currentText()])
        self.output_path = str(output)
        self._snapshot = snapshot
        self._thumbnail_path = ""
        self.output_label.setText(f"Output: {output}")
        self.progress_bar.setValue(0)
        self.progress_status.setText("Starting encoder…")
        self.progress_details.setText("Elapsed: 00:00:00")
        self.pages.setCurrentIndex(1)
        self.export_button.setEnabled(False)
        self.worker = ExportWorker(
            snapshot, str(self.root_dir), self.output_path, width, height,
            fps, options, self.thumbnail_mode.currentText(), self._custom_thumbnail,
            self._thumbnail_time if self.thumbnail_mode.currentText() == "Current project frame" else float(getattr(self.timeline, "playhead", 0.0)), self,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._export_succeeded)
        self.worker.failed.connect(self._export_failed)
        self.worker.start()

    def _on_progress(self, percent, stage, elapsed):
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self.progress_status.setText(stage)
        self.progress_details.setText(f"Elapsed: {elapsed}")

    def _export_succeeded(self, path, thumbnail_path):
        self._success_path = str(path)
        self._thumbnail_path = str(thumbnail_path or "")
        self.progress_bar.setValue(100)
        self.progress_status.setText("Export completed successfully." if self.thumbnail_mode.currentText() == "None" or self._thumbnail_path else "Video exported; thumbnail could not be generated.")
        details = f"Saved video: {path}"
        if self._thumbnail_path:
            details += f"\nThumbnail: {self._thumbnail_path}"
        elif self.thumbnail_mode.currentText() != "None":
            details += "\nThumbnail: not created; check that the selected playhead time contains visible media and FFmpeg is available."
        self.output_label.setText(details)
        self.progress_close_button.setText("Done")
        QMessageBox.information(self, "Export complete", details)
        self.export_button.setEnabled(True)

    def _export_failed(self, error):
        self.progress_status.setText("Export failed. Check the error details below.")
        self.output_label.setText(str(error)[-4000:])
        QMessageBox.critical(self, "Export failed", str(error)[-3000:])
        self.pages.setCurrentIndex(0)
        self.export_button.setEnabled(True)

    def _open_output_folder(self):
        folder = Path(self.output_path).parent if self.output_path else self.output_dir
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _close_progress(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Export in progress", "Please wait until exporting finishes.")
            return
        self.pages.setCurrentIndex(0)
        self.reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Export in progress", "Export is still running. Please wait until it finishes.")
            event.ignore()
            return
        super().closeEvent(event)
