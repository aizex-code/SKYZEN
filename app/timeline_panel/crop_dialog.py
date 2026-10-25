"""Interactive crop dialog for selected timeline video/image clips."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QRect, QPoint, QSize, QUrl, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QWidget, QDialogButtonBox, QSizePolicy, QSlider, QToolButton
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink


RATIOS = {
    "Free": None,
    "Original": "original",
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "1:1": 1.0,
    "4:5": 4 / 5,
}


class CropCanvas(QWidget):
    """Preview canvas with draggable crop rectangle and corner handles."""
    def __init__(self, pixmap: QPixmap, clip: dict, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.clip = clip
        self.setMinimumSize(420, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.ratio = None
        self._drag_mode = None
        self._drag_start = QPoint()
        self._start_rect = QRect()
        self._image_rect = QRect()
        self._crop_rect = QRect()
        self._preview_mode = False
        self._load_clip_rect()

    def set_preview_pixmap(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            return
        self.pixmap = QPixmap(pixmap)
        self._initialized = False
        self.update()

    def _load_clip_rect(self):
        w = max(1, self.width())
        h = max(1, self.height())
        left = float(self.clip.get("crop_left", 0.0))
        top = float(self.clip.get("crop_top", 0.0))
        right = float(self.clip.get("crop_right", 0.0))
        bottom = float(self.clip.get("crop_bottom", 0.0))
        self._crop_rect = QRect(
            round(left * w), round(top * h),
            max(1, round((1-left-right) * w)),
            max(1, round((1-top-bottom) * h)),
        )

    def _layout_rects(self):
        if self.pixmap.isNull():
            self._image_rect = self.rect().adjusted(20, 20, -20, -20)
        else:
            size = self.pixmap.size()
            size.scale(self.size() - QSize(36, 36), Qt.AspectRatioMode.KeepAspectRatio)
            self._image_rect = QRect(
                (self.width()-size.width())//2,
                (self.height()-size.height())//2,
                size.width(), size.height()
            )
        if self._crop_rect.isNull() or not self._crop_rect.isValid():
            self._crop_rect = self._image_rect.adjusted(0, 0, 0, 0)
        # Crop coordinates are normalized to the actual displayed source bounds.
        if not hasattr(self, "_initialized") or not self._initialized:
            l = float(self.clip.get("crop_left", 0.0))
            t = float(self.clip.get("crop_top", 0.0))
            r = float(self.clip.get("crop_right", 0.0))
            b = float(self.clip.get("crop_bottom", 0.0))
            ir = self._image_rect
            self._crop_rect = QRect(
                ir.x()+round(l*ir.width()), ir.y()+round(t*ir.height()),
                max(24, round((1-l-r)*ir.width())),
                max(24, round((1-t-b)*ir.height()))
            )
            self._initialized = True
        self._crop_rect = self._crop_rect.intersected(self._image_rect)

    def set_ratio(self, ratio):
        self.ratio = ratio
        self._layout_rects()
        if ratio and ratio != "original":
            r = float(ratio)
            rect = self._crop_rect
            if rect.width() / max(1, rect.height()) > r:
                nw = round(rect.height() * r)
                rect.setX(rect.center().x()-nw//2)
                rect.setWidth(nw)
            else:
                nh = round(rect.width() / r)
                rect.setY(rect.center().y()-nh//2)
                rect.setHeight(nh)
            self._crop_rect = rect.intersected(self._image_rect)
        elif ratio == "original" and not self.pixmap.isNull():
            self._crop_rect = self._image_rect.adjusted(0,0,0,0)
        self.update()

    def crop_values(self):
        self._layout_rects()
        ir, cr = self._image_rect, self._crop_rect.intersected(self._image_rect)
        if ir.width() < 1 or ir.height() < 1:
            return 0.0, 0.0, 0.0, 0.0
        return (
            max(0.0, min(.45, (cr.x()-ir.x())/ir.width())),
            max(0.0, min(.45, (cr.y()-ir.y())/ir.height())),
            max(0.0, min(.45, (ir.right()-cr.right())/ir.width())),
            max(0.0, min(.45, (ir.bottom()-cr.bottom())/ir.height())),
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111318"))
        self._layout_rects()
        ir = self._image_rect
        if not self.pixmap.isNull():
            p.drawPixmap(ir, self.pixmap)
        else:
            p.setPen(QColor("#AAB4C0"))
            p.drawText(ir, Qt.AlignmentFlag.AlignCenter, "Preview unavailable\nCrop will still be applied to the selected clip")
        cr = self._crop_rect.intersected(ir)
        if self._preview_mode and cr.isValid() and not self.pixmap.isNull():
            # When the pointer leaves the crop editor, show the selected crop
            # enlarged to the full preview area, like the actual output frame.
            sx = round((cr.x() - ir.x()) * self.pixmap.width() / max(1, ir.width()))
            sy = round((cr.y() - ir.y()) * self.pixmap.height() / max(1, ir.height()))
            sw = max(1, round(cr.width() * self.pixmap.width() / max(1, ir.width())))
            sh = max(1, round(cr.height() * self.pixmap.height() / max(1, ir.height())))
            source = QRect(sx, sy, sw, sh).intersected(self.pixmap.rect())
            p.fillRect(ir, QColor("#111318"))
            p.drawPixmap(ir, self.pixmap, source)
            p.end()
            return
        p.fillRect(ir, QColor(0, 0, 0, 95))
        if cr.isValid():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(cr, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if not self.pixmap.isNull():
                p.save()
                p.setClipRect(cr)
                p.drawPixmap(ir, self.pixmap)
                p.restore()
            p.setPen(QPen(QColor("#40E8FF"), 2))
            p.drawRect(cr)
            p.setPen(QPen(QColor(220, 245, 255, 150), 1, Qt.PenStyle.DashLine))
            for i in (1, 2):
                x = cr.x() + cr.width()*i/3
                y = cr.y() + cr.height()*i/3
                p.drawLine(round(x), cr.top(), round(x), cr.bottom())
                p.drawLine(cr.left(), round(y), cr.right(), round(y))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#EAFBFF"))
            for pt in (cr.topLeft(), cr.topRight(), cr.bottomLeft(), cr.bottomRight()):
                p.drawRect(pt.x()-5, pt.y()-5, 10, 10)
        p.end()

    def leaveEvent(self, event):
        # Outside the crop handles, preview the selected area at fit-to-panel
        # scale. Returning to the canvas restores the draggable crop overlay.
        self._preview_mode = True
        self.update()
        super().leaveEvent(event)

    def enterEvent(self, event):
        self._preview_mode = False
        self.update()
        super().enterEvent(event)

    def _handle_at(self, pos):
        r = self._crop_rect
        handles = {
            "tl": r.topLeft(), "tr": r.topRight(),
            "bl": r.bottomLeft(), "br": r.bottomRight(),
        }
        for key, point in handles.items():
            if (pos-point).manhattanLength() <= 16:
                return key
        if r.contains(pos):
            return "move"
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._layout_rects()
        self._drag_mode = self._handle_at(event.position().toPoint())
        if self._drag_mode is None and self._image_rect.contains(event.position().toPoint()):
            self._drag_mode = "br"
            self._crop_rect = QRect(event.position().toPoint(), QSize(1,1))
        self._drag_start = event.position().toPoint()
        self._start_rect = QRect(self._crop_rect)
        self.update()

    def mouseMoveEvent(self, event):
        if not self._drag_mode:
            return
        pos = event.position().toPoint()
        ir = self._image_rect
        if self._drag_mode == "move":
            delta = pos-self._drag_start
            r = QRect(self._start_rect)
            r.translate(delta)
            if r.left() < ir.left(): r.moveLeft(ir.left())
            if r.top() < ir.top(): r.moveTop(ir.top())
            if r.right() > ir.right(): r.moveRight(ir.right())
            if r.bottom() > ir.bottom(): r.moveBottom(ir.bottom())
            self._crop_rect = r
        else:
            r = QRect(self._start_rect)
            if self._drag_mode in ("tl", "bl"): r.setLeft(pos.x())
            if self._drag_mode in ("tr", "br"): r.setRight(pos.x())
            if self._drag_mode in ("tl", "tr"): r.setTop(pos.y())
            if self._drag_mode in ("bl", "br"): r.setBottom(pos.y())
            r = r.normalized().intersected(ir)
            if r.width() >= 24 and r.height() >= 24:
                if self.ratio and self.ratio != "original":
                    ratio = float(self.ratio)
                    if r.width()/r.height() > ratio:
                        r.setWidth(round(r.height()*ratio))
                    else:
                        r.setHeight(round(r.width()/ratio))
                self._crop_rect = r
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag_mode = None


class CropFilmstrip(QWidget):
    """Compact timeline-style preview strip with a real source playhead."""
    seekRequested = Signal(float)
    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.setMinimumHeight(76)
        self.setMaximumHeight(94)
        self.setMouseTracking(True)
        self.playhead = 0.5
        self.range_start = 0.18
        self.range_end = 0.82
        self._drag = None
        self._last_x = 0

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#15181D"))
        outer = self.rect().adjusted(7, 7, -7, -22)
        if outer.width() <= 0 or outer.height() <= 0:
            p.end()
            return
        # Filmstrip tiles mimic a source timeline. For videos the current
        # thumbnail is reused as a lightweight fallback; no blocking decode.
        count = max(1, min(12, outer.width() // 58))
        tile_w = outer.width() / count
        for i in range(count):
            target = QRect(round(outer.x()+i*tile_w), outer.y(),
                           max(1, round(tile_w)+1), outer.height())
            if not self.pixmap.isNull():
                p.drawPixmap(target, self.pixmap)
            else:
                p.fillRect(target, QColor("#252A31"))
            p.setPen(QPen(QColor("#171A20"), 1))
            p.drawRect(target)
        sx = outer.x() + round(self.range_start * outer.width())
        ex = outer.x() + round(self.range_end * outer.width())
        # Dim outside selected range, outline the usable range.
        p.fillRect(QRect(outer.left(), outer.top(), max(0, sx-outer.left()), outer.height()), QColor(0,0,0,135))
        p.fillRect(QRect(ex, outer.top(), max(0, outer.right()-ex), outer.height()), QColor(0,0,0,135))
        p.setPen(QPen(QColor("#40E8FF"), 2))
        p.drawLine(sx, outer.top(), sx, outer.bottom())
        p.drawLine(ex, outer.top(), ex, outer.bottom())
        p.drawLine(sx, outer.top(), ex, outer.top())
        p.drawLine(sx, outer.bottom(), ex, outer.bottom())
        p.setBrush(QColor("#EAFBFF"))
        p.setPen(Qt.PenStyle.NoPen)
        for x in (sx, ex):
            p.drawRoundedRect(QRect(x-4, outer.center().y()-8, 8, 16), 2, 2)
        px = outer.x() + round(self.playhead * outer.width())
        p.setPen(QPen(QColor("#40E8FF"), 2))
        p.drawLine(px, outer.top()-3, px, outer.bottom()+2)
        p.setBrush(QColor("#40E8FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon([QPoint(px-5, outer.top()-5), QPoint(px+5, outer.top()-5), QPoint(px, outer.top()+2)])
        p.setPen(QColor("#9AA6B4"))
        p.drawText(QRect(outer.left(), outer.bottom()+3, outer.width(), 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "SOURCE PREVIEW")
        p.drawText(QRect(outer.left(), outer.bottom()+3, outer.width(), 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Timeline")
        p.end()

    def mousePressEvent(self, event):
        x = event.position().x()
        outer = self.rect().adjusted(7, 7, -7, -22)
        if outer.width() <= 0:
            return
        sx = outer.x() + self.range_start * outer.width()
        ex = outer.x() + self.range_end * outer.width()
        if abs(x-sx) < 12:
            self._drag = "start"
        elif abs(x-ex) < 12:
            self._drag = "end"
        else:
            self._drag = "playhead"
        self._update_x(x)
        self.seekRequested.emit(self.playhead)
        self._last_x = x

    def mouseMoveEvent(self, event):
        if self._drag:
            self._update_x(event.position().x())
            if self._drag == "playhead":
                self.seekRequested.emit(self.playhead)

    def set_playhead(self, fraction):
        self.playhead = max(0.0, min(1.0, float(fraction)))
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def _update_x(self, x):
        outer = self.rect().adjusted(7, 7, -7, -22)
        value = max(0.0, min(1.0, (x-outer.x()) / max(1, outer.width())))
        if self._drag == "start":
            self.range_start = min(value, self.range_end - 0.05)
        elif self._drag == "end":
            self.range_end = max(value, self.range_start + 0.05)
        else:
            self.playhead = value
        self.update()


class CropDialog(QDialog):
    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.clip = timeline.selected_clip
        self.setWindowTitle("Crop")
        self.resize(760, 520)
        self.setMinimumSize(560, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(12,12,12,12)
        root.setSpacing(8)
        heading = QLabel("CROP  ·  Drag the corners to crop")
        heading.setStyleSheet("font-size:13px;font-weight:700;color:#40E8FF;")
        root.addWidget(heading)
        row = QHBoxLayout()
        row.addWidget(QLabel("Aspect ratio"))
        self.ratio_box = QComboBox()
        self.ratio_box.addItems(list(RATIOS))
        self.ratio_box.setMinimumWidth(120)
        row.addWidget(self.ratio_box)
        row.addStretch()
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset_crop)
        row.addWidget(reset)
        root.addLayout(row)

        path = Path(str(self.clip.get("path", "")))
        pix = QPixmap()
        if str(self.clip.get("kind", "")).lower() == "image":
            pix = QPixmap(str(path))
        if pix.isNull():
            window = timeline.window()
            service = getattr(window, "thumbnail_service", None)
            if service is not None:
                try: pix = service.request(path)
                except Exception: pass
        self.canvas = CropCanvas(pix, self.clip)
        self.canvas.setStyleSheet("border:1px solid #303944;border-radius:4px;")
        root.addWidget(self.canvas, 1)
        # A compact filmstrip/playhead row beneath the crop canvas, matching
        # the reference's source timeline without running expensive decodes.
        self.filmstrip = CropFilmstrip(pix, self)
        root.addWidget(self.filmstrip)

        playback_row = QHBoxLayout()
        self.preview_play_button = QToolButton()
        self.preview_play_button.setText("▶")
        self.preview_play_button.setToolTip("Play or pause source preview")
        self.preview_play_button.setFixedSize(32, 26)
        self.preview_play_button.clicked.connect(self._toggle_preview_playback)
        playback_row.addWidget(self.preview_play_button)
        self.preview_time = QLabel("00:00.00 / 00:00.00")
        self.preview_time.setStyleSheet("color:#40E8FF;font-size:10px;")
        playback_row.addWidget(self.preview_time)
        playback_row.addStretch()
        self.preview_seek = QSlider(Qt.Orientation.Horizontal)
        self.preview_seek.setRange(0, 1000)
        self.preview_seek.setFixedWidth(220)
        self.preview_seek.sliderMoved.connect(self._seek_preview_slider)
        playback_row.addWidget(self.preview_seek)
        root.addLayout(playback_row)

        self.preview_player = None
        self.preview_sink = None
        self.preview_audio = None
        if str(self.clip.get("kind", "")).lower() == "video" and path.is_file():
            try:
                self.preview_player = QMediaPlayer(self)
                self.preview_sink = QVideoSink(self)
                self.preview_audio = QAudioOutput(self)
                self.preview_audio.setMuted(True)
                self.preview_player.setAudioOutput(self.preview_audio)
                self.preview_player.setVideoOutput(self.preview_sink)
                self.preview_sink.videoFrameChanged.connect(self._on_preview_frame)
                self.preview_player.positionChanged.connect(self._on_preview_position)
                self.preview_player.durationChanged.connect(self._on_preview_duration)
                self.preview_player.setSource(QUrl.fromLocalFile(str(path)))
            except Exception:
                self.preview_player = None

        self.filmstrip.seekRequested.connect(self._seek_preview_fraction)
        self.ratio_box.currentTextChanged.connect(lambda key: self.canvas.set_ratio(RATIOS[key]))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_crop)
        root.addWidget(buttons)

    def _on_preview_frame(self, frame):
        try:
            image = frame.toImage()
            if not image.isNull():
                self.canvas.set_preview_pixmap(QPixmap.fromImage(image))
        except Exception:
            pass

    def _on_preview_position(self, position):
        player = self.preview_player
        if player is None:
            return
        duration = max(1, int(player.duration()))
        fraction = max(0.0, min(1.0, float(position) / duration))
        self.filmstrip.set_playhead(fraction)
        if not self.preview_seek.isSliderDown():
            self.preview_seek.blockSignals(True)
            self.preview_seek.setValue(round(fraction * 1000))
            self.preview_seek.blockSignals(False)
        self.preview_time.setText(
            f"{position/1000:06.2f} / {player.duration()/1000:06.2f}"
        )

    def _on_preview_duration(self, duration):
        if duration <= 0:
            self.preview_time.setText("00:00.00 / 00:00.00")

    def _toggle_preview_playback(self):
        if self.preview_player is None:
            return
        if self.preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.preview_player.pause()
            self.preview_play_button.setText("▶")
        else:
            self.preview_player.play()
            self.preview_play_button.setText("Ⅱ")

    def _seek_preview_slider(self, value):
        if self.preview_player is not None and self.preview_player.duration() > 0:
            self.preview_player.setPosition(round(self.preview_player.duration() * value / 1000))

    def _seek_preview_fraction(self, fraction):
        if self.preview_player is not None and self.preview_player.duration() > 0:
            self.preview_player.setPosition(round(self.preview_player.duration() * fraction))

    def reset_crop(self):
        self.clip["crop_left"] = self.clip["crop_top"] = 0.0
        self.clip["crop_right"] = self.clip["crop_bottom"] = 0.0
        self.canvas._initialized = False
        self.canvas.update()

    def closeEvent(self, event):
        try:
            if self.preview_player is not None:
                self.preview_player.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def apply_crop(self):
        left, top, right, bottom = self.canvas.crop_values()
        self.timeline._push_history()
        self.clip["crop_left"] = left
        self.clip["crop_top"] = top
        self.clip["crop_right"] = right
        self.clip["crop_bottom"] = bottom
        self.timeline.rebuild(keep_view=True)
        try:
            self.timeline._emit_active_clips(self.timeline.playhead)
            self.timeline.clip_selected.emit(
                str(self.clip.get("path", "")), float(self.clip.get("start", 0)),
                float(self.clip.get("duration", 0)), str(self.clip.get("kind", "Video"))
            )
        except Exception:
            pass
        self.accept()
