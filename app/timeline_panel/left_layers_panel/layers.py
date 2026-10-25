from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QPoint, QTimer, QSignalBlocker, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget, QSizePolicy
)

# These are imported from core after ClipWidget/TrackArea have been defined.
# core.py imports this module only after those definitions, avoiding a hard
# dependency on TimelinePanel during module initialization.
from ..core import COLORS, detect_kind, ClipWidget, TrackArea
from ..track_layout import shared_row_geometry


def _is_main_track(track):
    """Recognize the base lane in current and legacy project track data."""
    if not isinstance(track, dict):
        return False
    if bool(track.get("is_main", False)):
        return True
    name = str(track.get("name", "")).strip().casefold()
    return name == "main" or name.endswith(" - main") or name.endswith(" main")


def _shared_row_geometry(timeline):
    """Compatibility alias; all timeline columns use the canonical row model."""
    return shared_row_geometry(timeline)


class LayerHeader(QFrame):
    def __init__(self, track: dict, timeline: "TimelinePanel", parent=None):
        super().__init__(parent)
        self.track = track
        self.timeline = timeline

        from ..track_layout import row_height
        self.setFixedHeight(row_height(timeline, track))
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.setStyleSheet(
            f"""
            QFrame {{
                background:#212123;
                border-right:1px solid #2A2E34;
                border-bottom:1px solid #2A2E34;
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 4, 0)
        layout.setSpacing(2)

        type_btn = QToolButton()
        track_type = str(track.get("track_type", ""))
        type_btn.setText(
            {"Text": "T", "Effects": "✦", "Filters": "◈", "Adjustments": "◐"}.get(
                track_type, "✦" if track["base"] == "E" else ("▣" if track["base"] == "V" else "♫")
            )
        )
        type_btn.setFixedSize(18, 20)
        type_btn.setStyleSheet(
            """
            QToolButton {
                color:#A5B0BC;
                background:transparent;
                border:0;
                font-size:12px;
                padding:0;
            }
            """
        )
        display_name = (
            f"{track['name']}  ·  MAIN"
            if _is_main_track(track)
            else track["name"]
        )
        name = QLabel(display_name)
        name.setStyleSheet(
            f"color:{COLORS['text']};"
            "font-size:9px;"
            "font-weight:650;"
        )
        name.setAlignment(
            Qt.AlignmentFlag.AlignVCenter
            | Qt.AlignmentFlag.AlignLeft
        )
        name.setMinimumWidth(18)
        source_names = [
            Path(str(clip.get("path", ""))).name
            for clip in track.get("clips", [])
            if clip.get("path")
        ]
        tooltip = display_name
        if source_names:
            tooltip += "\\nMedia: " + "\\n".join(source_names[:8])
            if len(source_names) > 8:
                tooltip += f"\\n… and {len(source_names) - 8} more"
        tooltip += f"\\nVolume: {float(track.get('volume', 1.0)) * 100:.0f}%"
        if track.get("muted", False):
            tooltip += "\\nMuted"

        layout.addWidget(type_btn)
        layout.addWidget(name, 1)

        lock = QToolButton()
        lock.setText("🔒")
        lock.setFixedSize(18, 20)
        lock.setCheckable(True)
        lock_blocker = QSignalBlocker(lock)
        lock.setChecked(
            bool(track.get("locked", False))
        )
        del lock_blocker
        lock.setStyleSheet(
            """
            QToolButton {
                color:#7C8997;
                background:transparent;
                border:0;
                font-size:11px;
                padding:0;
            }
            QToolButton:checked {
                color:#EFF5FA;
                background:#19212B;
                border-radius:4px;
            }
            """
        )
        lock.toggled.connect(
            lambda checked: timeline.set_track_locked(
                track,
                checked,
            )
        )
        layout.addWidget(lock)

        hide = QToolButton()
        hide.setText("⊘" if track.get("hidden", False) else "◉")
        hide.setFixedSize(21, 22)
        hide.setToolTip("Show layer" if track.get("hidden", False) else "Hide layer")
        hide.setCheckable(True)
        hide_blocker = QSignalBlocker(hide)
        hide.setChecked(
            bool(track.get("hidden", False))
        )
        del hide_blocker
        hide.setStyleSheet(
            """
            QToolButton {
                color:#7C8997;
                background:transparent;
                border:0;
                font-size:15px;
                font-weight:700;
                padding:0;
            }
            QToolButton:checked {
                color:#EFF5FA;
                background:#19212B;
                border-radius:4px;
            }
            """
        )
        def toggle_layer_visibility(hidden, button=hide, target_track=track):
            button.setText("⊘" if hidden else "◉")
            button.setToolTip("Show layer" if hidden else "Hide layer")
            timeline.set_track_hidden(target_track, hidden)

        hide.toggled.connect(toggle_layer_visibility)
        layout.addWidget(hide)

        mute = QToolButton()
        mute.setText(
            "🔇" if track.get("muted", False)
            else "🔊"
        )
        mute.setFixedSize(18, 20)
        mute.setCheckable(True)
        mute_blocker = QSignalBlocker(mute)
        mute.setChecked(
            bool(track.get("muted", False))
        )
        del mute_blocker
        mute.setStyleSheet(
            """
            QToolButton {
                color:#7C8997;
                background:transparent;
                border:0;
                font-size:11px;
                padding:0;
            }
            QToolButton:checked {
                color:#FF9E9E;
                background:#24191D;
                border-radius:4px;
            }
            """
        )
        mute.toggled.connect(
            lambda checked: (
                setattr(
                    mute,
                    "text",
                    "🔇" if checked else "🔊",
                ),
                timeline.set_track_muted(
                    track,
                    checked,
                ),
            )
        )
        layout.addWidget(mute)

        more = QToolButton()
        more.setText("⋮")
        more.setFixedSize(18, 20)
        more.setStyleSheet(
            """
            QToolButton {
                color:#8793A0;
                background:transparent;
                border:0;
                font-size:16px;
                font-weight:700;
                padding:0;
            }
            QToolButton:hover {
                color:#F4F8FC;
                background:#202832;
                border-radius:4px;
            }
            """
        )
        more.clicked.connect(
            lambda: timeline.show_track_context_menu(
                track,
                more.mapToGlobal(
                    QPoint(
                        more.width(),
                        more.height(),
                    )
                ),
            )
        )
        layout.addWidget(more)

        # Wheel gestures over labels/buttons must scroll the same master
        # timeline scrollbar, otherwise the controls can appear detached from
        # the clip rows when users scroll over the left layer column.
        self.installEventFilter(self)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            if self.timeline._scroll_timeline_wheel(event):
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        if self.timeline._scroll_timeline_wheel(event):
            return
        event.ignore()

    def contextMenuEvent(self, event):
        self.timeline.show_track_context_menu(
            self.track,
            event.globalPos(),
        )
        event.accept()




# ============================================================
# Time ruler
# ============================================================


class LayerAddDropButton(QToolButton):
    """Compact top drop target used to create a new layer immediately."""

    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setAcceptDrops(True)

    @staticmethod
    def _media_from_mime(mime):
        if mime.hasFormat("application/x-skyzen-media"):
            try:
                raw = bytes(
                    mime.data("application/x-skyzen-media")
                ).decode("utf-8", errors="replace")
                kind, path = raw.split("|", 1)
                return kind, path
            except Exception:
                return None, None
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                return detect_kind(Path(path)), path
        return None, None

    def dragEnterEvent(self, event):
        kind, path = self._media_from_mime(event.mimeData())
        if kind and path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        kind, path = self._media_from_mime(event.mimeData())
        if kind and path:
            # The icon is a stack-creation command; placement time is the
            # current project playhead, not the tiny button's x coordinate.
            self.timeline._drop_new_track(
                path,
                kind,
                self.timeline.playhead,
            )
            event.acceptProposedAction()
        else:
            event.ignore()


class LayerInsertionGap(QFrame):
    """Non-track separator that becomes a new-layer insertion target on hold."""

    def __init__(self, timeline, display_gap_index, before_track=None, parent=None, section="overlay"):
        super().__init__(parent)
        self.timeline = timeline
        self.display_gap_index = int(display_gap_index)
        self.before_track = before_track
        self.section = str(section or "overlay")
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFixedHeight(timeline.LAYER_INSERT_GAP_HEIGHT)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(timeline.LAYER_INSERT_HOLD_MS)
        self._hold_timer.timeout.connect(self._show_preview)
        self._preview = None
        self._last_pos = QPoint()
        self._active_kind = None
        self._active_path = None
        self._inside = False

        self.setStyleSheet(
            """
            QFrame {
                background:#1B1D20;
                border-top:1px solid #25282D;
                border-bottom:1px solid #25282D;
            }
            QFrame:hover {
                background:#25292E;
                border-top:1px solid #30363D;
                border-bottom:1px solid #30363D;
            }
            """
        )

    @staticmethod
    def _tool_from_mime(mime):
        if not mime.hasFormat("application/x-skyzen-tool-asset"):
            return None
        try:
            import json
            payload = json.loads(bytes(mime.data("application/x-skyzen-tool-asset")).decode("utf-8", "replace"))
            tool_type = str(payload.get("tool_type", ""))
            preset_id = str(payload.get("preset_id", ""))
            if tool_type in ("Text", "Effects", "Filters", "Adjustments") and preset_id:
                return tool_type, preset_id
        except Exception:
            pass
        return None

    @staticmethod
    def _media_from_mime(mime):
        if mime.hasFormat("application/x-skyzen-media"):
            try:
                raw = bytes(
                    mime.data("application/x-skyzen-media")
                ).decode("utf-8", errors="replace")
                kind, path = raw.split("|", 1)
                return kind, path
            except Exception:
                return None, None
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                return detect_kind(Path(path)), path
        return None, None

    def _accepts_kind(self, kind):
        kind_base = self.timeline._track_base_for_kind(kind)
        if self.section == "audio":
            return kind_base == "A"
        if self.section == "overlay":
            return kind_base == "V"
        return False

    def _hide_preview(self):
        if self._preview is not None:
            self._preview.hide()

    def _clear_hold(self):
        self._hold_timer.stop()
        self._active_kind = None
        self._active_path = None
        self._hide_preview()

    def dragEnterEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool and self.section == "overlay":
            self._inside = True
            self._clear_hold()
            event.acceptProposedAction()
            return
        kind, path = self._media_from_mime(event.mimeData())
        if kind and path and self._accepts_kind(kind):
            self._inside = True
            self._active_kind = kind
            self._active_path = path
            self._last_pos = event.position().toPoint()
            # Preview immediately; a new layer is committed only on drop.
            self._show_preview()
            event.acceptProposedAction()
        else:
            self._inside = False
            self._clear_hold()
            event.ignore()

    def dragMoveEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool and self.section == "overlay":
            self._inside = True
            event.acceptProposedAction()
            return
        kind, path = self._media_from_mime(event.mimeData())
        if not kind or not path or not self._accepts_kind(kind):
            self._inside = False
            self._clear_hold()
            event.ignore()
            return
        self._active_kind = kind
        self._active_path = path
        self._last_pos = event.position().toPoint()
        if self._preview is None:
            self._show_preview()
        else:
            self._position_preview()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._inside = False
        self._clear_hold()
        super().dragLeaveEvent(event)

    def _show_preview(self):
        if not self._inside or not self._active_kind:
            return
        if self._preview is None:
            self._preview = QLabel(self.timeline.content)
            self._preview.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                True,
            )
            self._preview.setAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            # Render a complete temporary lane, not a small tooltip-like label.
            # It remains a visual-only widget: no track data is created until drop.
            self._preview.setStyleSheet(
                """
                QLabel {
                    color:#DFFBFF;
                    background:rgba(41, 57, 65, 210);
                    border-top:1px dashed #16D6E8;
                    border-bottom:1px dashed #16D6E8;
                    border-left:1px dashed #16D6E8;
                    border-right:1px dashed #16D6E8;
                    border-radius:2px;
                    font-size:10px;
                    font-weight:600;
                    padding-left:12px;
                }
                """
            )

        label = (
            "♫   Release to create audio layer"
            if self._active_kind == "Audio"
            else "▣   Release to create overlay layer"
        )
        self._preview.setText(label)
        ghost_height = int(self.timeline.TRACK_HEIGHT)
        self._preview.setGeometry(
            0, 0, max(1, self.timeline.content.width()), ghost_height
        )
        self._preview.show()
        self._preview.raise_()
        self._position_preview()

    def _position_preview(self):
        if self._preview is None or not self._preview.isVisible():
            return
        gap_pos = self.mapTo(self.timeline.content, QPoint(0, 0))
        # The insertion target is only 3px tall at rest. During dragging, expand
        # its visual feedback into a full-height timeline lane so the user can
        # clearly see where the new overlay would be inserted. This widget is
        # transient and never mutates the track model unless dropEvent commits.
        x = 0
        y = gap_pos.y() + (self.height() - self._preview.height()) // 2
        self._preview.setGeometry(
            x, y, max(1, self.timeline.content.width()),
            int(self.timeline.TRACK_HEIGHT),
        )

    def dropEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool and self.section == "overlay":
            gap_origin = self.mapTo(self.timeline.content, QPoint(0, 0))
            content_x = gap_origin.x() + event.position().x()
            start = self.timeline.x_to_time(content_x)
            try:
                self.timeline.add_tool_asset_at_time(tool[0], tool[1], start, self.before_track)
            except Exception as exc:
                self.timeline._log_drop_failure("typed tool insertion-gap drop", exc)
                event.ignore()
            else:
                event.acceptProposedAction()
            self._inside = False
            self._clear_hold()
            return
        kind, path = self._media_from_mime(event.mimeData())
        allowed = bool(
            kind and path and self._accepts_kind(kind)
            and self._preview is not None and self._preview.isVisible()
        )
        if allowed:
            gap_origin = self.mapTo(self.timeline.content, QPoint(0, 0))
            content_x = gap_origin.x() + event.position().x()
            start = self.timeline.x_to_time(content_x)
            try:
                self.timeline.insert_media_as_new_layer(
                    path, kind, start,
                    display_gap_index=self.display_gap_index,
                    before_track=self.before_track,
                )
            except Exception as exc:
                self.timeline._log_drop_failure("insertion-gap drop", exc)
                event.ignore()
            else:
                event.acceptProposedAction()
        else:
            event.ignore()
        self._inside = False
        self._clear_hold()



class TopLayerDropArea(QFrame):
    """Dedicated new-layer creation zone directly beneath the ruler."""

    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setAcceptDrops(True)
        self.setFixedHeight(timeline.TOP_LAYER_DROP_HEIGHT)
        self.setMouseTracking(True)
        self.setStyleSheet(
            f"""
            QFrame {{
                background:#242424;
                border-top:1px solid #3A3A3A;
                border-bottom:1px solid #3A3A3A;
            }}
            QFrame:hover {{ background:#292929; }}
            """
        )
        # Keep this insertion zone visually quiet. The centered empty-state
        # hint is the only on-canvas message when the timeline has no media.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    @staticmethod
    def _tool_from_mime(mime):
        if not mime.hasFormat("application/x-skyzen-tool-asset"):
            return None
        try:
            import json
            payload = json.loads(bytes(mime.data("application/x-skyzen-tool-asset")).decode("utf-8", "replace"))
            tool_type = str(payload.get("tool_type", ""))
            preset_id = str(payload.get("preset_id", ""))
            if tool_type in ("Text", "Effects", "Filters", "Adjustments") and preset_id:
                return tool_type, preset_id
        except Exception:
            pass
        return None

    @staticmethod
    def _media_from_mime(mime):
        if mime.hasFormat("application/x-skyzen-media"):
            try:
                kind, path = bytes(mime.data("application/x-skyzen-media")).decode("utf-8", "replace").split("|", 1)
                return kind, path
            except Exception:
                return None, None
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                return detect_kind(Path(path)), path
        return None, None

    def dragEnterEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool:
            event.acceptProposedAction()
            return
        kind, path = self._media_from_mime(event.mimeData())
        if kind and path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool:
            start = self.timeline.x_to_time(float(event.position().x()))
            try:
                self.timeline.add_tool_asset_at_time(tool[0], tool[1], start, None)
            except Exception as exc:
                self.timeline._log_drop_failure("top typed-tool drop", exc)
                event.ignore()
                return
            event.acceptProposedAction()
            return
        kind, path = self._media_from_mime(event.mimeData())
        if not kind or not path:
            event.ignore()
            return
        # The drop target is media-compatible: videos/images create visual lanes;
        # audio is routed by the model into the audio stack below Main.
        start = self.timeline.x_to_time(float(event.position().x()))
        try:
            self.timeline._drop_new_track(path, kind, start)
        except Exception as exc:
            self.timeline._log_drop_failure("top compatible-layer drop", exc)
            event.ignore()
            return
        event.acceptProposedAction()



class TimelineSectionRow(QFrame):
    """Non-track section divider shared by the timeline column."""
    def __init__(self, title, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setFixedHeight(timeline.SECTION_HEADER_HEIGHT)
        self.setStyleSheet(
            "QFrame{background:#10151C;border-top:1px solid #252D37;border-bottom:1px solid #252D37;}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        label = QLabel(title)
        label.setStyleSheet("color:#6F7E8E;font-size:8px;font-weight:800;letter-spacing:1px;border:0;")
        layout.addWidget(label)
        layout.addStretch()



class EffectDropRow(QFrame):
    """Reserved effect lane area; it is UI-only until the effect engine is enabled."""
    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setFixedHeight(timeline.EFFECT_DROP_HEIGHT)
        self.setAcceptDrops(True)
        self.setStyleSheet("QFrame{background:#0C1016;border-bottom:1px solid #202832;} QFrame:hover{background:#111821;}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        label = QLabel("Drop an effect here  ·  effect lanes will link to active media layers")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color:#667585;font-size:9px;border:0;")
        layout.addWidget(label)



class TimelineContent(QWidget):
    def __init__(self, timeline: "TimelinePanel", parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setObjectName("TimelineContent")
        self.setAcceptDrops(True)
        self.main_area = None
        self._main_track = None
        self._row_widgets = []

        self.top_layer_drop = TopLayerDropArea(self.timeline, self)
        self.empty = QLabel(
            "Drag media here to start editing\nor use + Edit Layer", self
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(70)
        self.empty.setAcceptDrops(True)
        self.empty.dragEnterEvent = self._drop_new_drag_enter
        self.empty.dropEvent = self._drop_new_drop
        self.empty.setStyleSheet(
            f"QLabel{{color:{COLORS['muted']};font-size:12px;"
            f"background:{COLORS['track']};border:0;}}"
        )
        self.drop_new = QFrame(self)
        self.drop_new.setAcceptDrops(False)
        self.drop_new.setStyleSheet(
            f"QFrame{{background:{COLORS['background']};"
            f"border-top:1px solid {COLORS['border']};}}"
        )
        drop_layout = QVBoxLayout(self.drop_new)
        drop_layout.setContentsMargins(8, 2, 8, 2)
        drop_label = QLabel("Drop below the layers to create a new compatible layer")
        drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_label.setStyleSheet(
            f"color:{COLORS['muted']};font-size:9px;border:0;"
        )
        drop_layout.addWidget(drop_label)

        self._zero_boundary = QFrame(self)
        self._zero_boundary.setFixedWidth(1)
        self._zero_boundary.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._zero_boundary.setStyleSheet("QFrame{background:#69727D;border:0;}")
        self._playhead_line = QFrame(self)
        self._playhead_line.setFixedWidth(2)
        self._playhead_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._playhead_line.setStyleSheet(
            f"QFrame{{background:{COLORS['cyan']};border:0;}}"
        )
        self._preview_line = QFrame(self)
        self._preview_line.setFixedWidth(1)
        self._preview_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._preview_line.setStyleSheet("QFrame{background:#FFFFFF55;border:0;}")
        self._preview_line.hide()
        # New overlay layers are created through the explicit narrow insertion
        # gaps; the empty-project drop target remains available for first media.


    def _drop_new_drag_enter(self, event):
        if (
            event.mimeData().hasFormat("application/x-skyzen-media")
            or event.mimeData().hasUrls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _drop_new_drop(self, event):
        start = self.timeline.x_to_time(event.position().x())
        if event.mimeData().hasFormat("application/x-skyzen-media"):
            raw = bytes(
                event.mimeData().data("application/x-skyzen-media")
            ).decode("utf-8", errors="replace")
            try:
                kind, path = raw.split("|", 1)
            except ValueError:
                event.ignore()
                return
            try:
                self.timeline._drop_new_track(path, kind, start)
            except Exception as exc:
                self.timeline._log_drop_failure("bottom layer drop", exc)
                event.ignore()
                return
            event.acceptProposedAction()
            return

        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                try:
                    self.timeline._drop_new_track(path, detect_kind(Path(path)), start)
                except Exception as exc:
                    self.timeline._log_drop_failure("bottom layer URL drop", exc)
                    event.ignore()
                    return
                event.acceptProposedAction()
                return
        event.ignore()

    def rebuild(self):
        for widget in self._row_widgets:
            widget.hide()
            widget.deleteLater()
        self._row_widgets = []
        self.main_area = None
        self._main_track = None
        self.sticky_main_widget = None
        self.sticky_audio_widget = None

        width = int(self.timeline.content_width())
        content_height = int(self.timeline.layer_content_height())
        self.setFixedSize(max(1, width), max(1, content_height))
        top_h = int(self.timeline.top_layer_drop_height())
        self.top_layer_drop.setFixedHeight(top_h)
        self.top_layer_drop.setGeometry(0, 0, width, top_h)
        self.top_layer_drop.setVisible(top_h > 0)
        self.empty.hide()
        self.drop_new.setFixedHeight(int(self.timeline.bottom_new_layer_height()))

        row_geometry, end_y = _shared_row_geometry(self.timeline)
        for kind, value, section, y, height, track_index, source_index in row_geometry:
            if kind == "section":
                widget = TimelineSectionRow(str(value), self.timeline, self)
            elif kind == "effect_drop":
                widget = EffectDropRow(self.timeline, self)
            elif kind == "gap":
                before = None
                source_rows = self.timeline.timeline_ui_rows()
                for future_kind, future_value, _future_section in source_rows[source_index + 1:]:
                    if future_kind == "track":
                        before = future_value
                        break
                widget = LayerInsertionGap(
                    self.timeline, max(0, track_index), before_track=before,
                    parent=self, section=section,
                )
            elif kind == "track":
                track = value
                widget = TrackArea(track, self.timeline, track_index, self)
                widget.dropped.connect(self.timeline.add_to_existing_track)
                if not track.get("hidden", False):
                    for clip in sorted(track.get("clips", []), key=lambda c: c["start"]):
                        clip_widget = ClipWidget(track, clip, self.timeline, widget)
                        start_x = self.timeline.time_to_x(clip["start"])
                        end_x = self.timeline.time_to_x(clip["start"] + clip["duration"])
                        from ..track_layout import clip_height
                        clip_h = clip_height(self.timeline, track)
                        clip_widget.setGeometry(
                            start_x,
                            max(self.timeline.CLIP_TOP_MARGIN, (height - clip_h) // 2),
                            max(2, end_x - start_x),
                            clip_h,
                        )
                        clip_widget.show()
            else:
                continue

            widget.setGeometry(0, y, width, height)
            widget.show()
            self._row_widgets.append(widget)
            if kind == "track" and value.get("is_main", False):
                self.sticky_main_widget = widget
            elif kind == "track" and value.get("base") == "A" and self.sticky_audio_widget is None:
                self.sticky_audio_widget = widget

        # Main is rendered in the same shared row loop as every other track.
        drop_y = max(0, content_height - self.drop_new.height())
        self.drop_new.setGeometry(0, drop_y, width, self.drop_new.height())
        # The bottom creation zone participates in the same scrolling stack.
        # The bottom drop zone mirrors the top insertion workspace and remains
        # available even in a one-track project.
        self.drop_new.setVisible(True)
        self._zero_boundary.setGeometry(0, 0, 1, content_height)
        self._zero_boundary.raise_()
        self._position_sticky_main()
        self._position_sticky_audio()
        self._move_playhead()
        hint = getattr(self.timeline, "empty_timeline_hint", None)
        if hint is not None:
            hint.refresh()


    def _position_sticky_main(self):
        """Hold Main at the bottom of the view; overlays pass behind it."""
        widget = getattr(self, "sticky_main_widget", None)
        if widget is None:
            return
        try:
            from ..track_layout import main_row_display_y
            positions = main_row_display_y(self.timeline)
            if positions is None:
                return
            _natural, y = positions
            if widget.y() != y:
                widget.move(widget.x(), int(y))
            widget.raise_()
            line = getattr(self, "_playhead_line", None)
            if line is not None:
                line.raise_()
            zero = getattr(self, "_zero_boundary", None)
            if zero is not None:
                zero.raise_()
        except RuntimeError:
            pass

    def _position_sticky_audio(self):
        """Audio rows are ordinary rows; only Main receives sticky positioning.

        Do not move or raise audio independently. When rows overlap the pinned
        Main row, Main is raised by _position_sticky_main and audio scrolls behind.
        """
        return

    def _drop_new_drag_enter(self, event):
        if event.mimeData().hasFormat("application/x-skyzen-media") or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _drop_new_drop(self, event):
        start = self.timeline.x_to_time(float(event.position().x()))
        if event.mimeData().hasFormat("application/x-skyzen-media"):
            try:
                raw = bytes(event.mimeData().data("application/x-skyzen-media")).decode("utf-8", errors="replace")
                kind, path = raw.split("|", 1)
            except ValueError:
                event.ignore()
                return
            self.timeline._drop_new_track(path, kind, start)
            event.acceptProposedAction()
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                self.timeline._drop_new_track(path, detect_kind(Path(path)), start)
                event.acceptProposedAction()
                return
        event.ignore()

    def dragEnterEvent(self, event):
        self._drop_new_drag_enter(event)

    def dragMoveEvent(self, event):
        self._drop_new_drag_enter(event)

    def dropEvent(self, event):
        self._drop_new_drop(event)

    def _move_playhead(self):
        x = self.timeline.time_to_x(self.timeline.playhead)
        self._playhead_line.setGeometry(
            x,
            0,
            2,
            max(1, self.height()),
        )
        self._playhead_line.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.timeline.select_clip(None)
            self.timeline.set_playhead(
                self.timeline.x_to_time(event.position().x()),
                ensure_visible=False,
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if self.timeline._scroll_timeline_wheel(event):
            return
        event.ignore()



class LayerEditGutterContent(QWidget):
    def __init__(self, timeline: "TimelinePanel", parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self._row_widgets = []
        self.main_cell = None
        self.sticky_main_widget = None
        self.sticky_audio_widget = None


    def wheelEvent(self, event):
        if self.timeline._scroll_timeline_wheel(event):
            return
        event.ignore()

    def rebuild(self):
        for widget in self._row_widgets:
            widget.hide()
            widget.deleteLater()
        self._row_widgets = []
        if self.main_cell is not None:
            self.main_cell.hide()
            self.main_cell.deleteLater()
        self.main_cell = None
        self.sticky_main_widget = None
        self.sticky_audio_widget = None

        width = int(self.timeline.EDIT_GUTTER_WIDTH)
        content_height = int(self.timeline.layer_content_height())
        self.setFixedSize(max(1, width), max(1, content_height))
        row_geometry, _end_y = _shared_row_geometry(self.timeline)
        for kind, value, _section, y, height, _track_index, _source_index in row_geometry:
            if kind == "track":
                cell = QFrame(self)
                cell.setStyleSheet(
                    f"QFrame{{background:{COLORS['background']};"
                    "border-bottom:1px solid #2A2E34;}}"
                )
                button = QToolButton(cell)
                button.setText("✎")
                button.setAutoRaise(True)
                button.setFixedSize(24, 24)
                button.setStyleSheet(
                    f"QToolButton{{color:{COLORS['muted']};background:transparent;"
                    "border:0;border-radius:4px;font-size:14px;padding:0;}"
                    f"QToolButton:hover{{color:{COLORS['text']};background:#171E27;}}"
                )
                button.clicked.connect(lambda checked=False, t=value: self.timeline.edit_layer(t))
                button.setGeometry(max(0, (width - 24) // 2), max(0, (height - 24) // 2), 24, 24)
                cell.setGeometry(0, y, width, height)
                cell.show()
                self._row_widgets.append(cell)
                if value.get("is_main", False):
                    self.sticky_main_widget = cell
                elif value.get("base") == "A" and self.sticky_audio_widget is None:
                    self.sticky_audio_widget = cell
            else:
                cell = QFrame(self)
                cell.setStyleSheet("QFrame{background:#10151C;border:0;}")
                cell.setGeometry(0, y, width, height)
                cell.show()
                self._row_widgets.append(cell)

        # Main edit controls are already built by the shared row loop.
        self._position_sticky_main()
        self._position_sticky_audio()

    def _position_sticky_main(self):
        """Mirror the timeline: Main's edit-icon row is pinned identically,
        so the lock/hide icons never drift from the Main clip row/label."""
        widget = getattr(self, "sticky_main_widget", None)
        if widget is None:
            return
        try:
            from ..track_layout import main_row_display_y
            positions = main_row_display_y(self.timeline)
            if positions is None:
                return
            _natural, y = positions
            if widget.y() != y:
                widget.move(widget.x(), int(y))
            widget.raise_()
        except RuntimeError:
            pass

    def _position_sticky_audio(self):
        """Audio edit controls scroll naturally with their audio rows."""
        return


class LayerSidebarContent(QWidget):
    def __init__(self, timeline: "TimelinePanel", parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self._row_widgets = []
        self.main_header = None
        self.sticky_main_widget = None
        self.sticky_audio_widget = None


    def wheelEvent(self, event):
        if self.timeline._scroll_timeline_wheel(event):
            return
        event.ignore()

    def rebuild(self):
        for widget in self._row_widgets:
            widget.hide()
            widget.deleteLater()
        self._row_widgets = []
        if self.main_header is not None:
            self.main_header.hide()
            self.main_header.deleteLater()
        self.main_header = None
        self.sticky_main_widget = None
        self.sticky_audio_widget = None

        width = int(self.timeline.HEADER_WIDTH)
        content_height = int(self.timeline.layer_content_height())
        self.setFixedSize(max(1, width), max(1, content_height))
        row_geometry, end_y = _shared_row_geometry(self.timeline)
        for kind, value, _section, y, height, _track_index, _source_index in row_geometry:
            if kind == "track":
                header = LayerHeader(value, self.timeline, self)
                header.setGeometry(0, y, width, height)
                header.show()
                self._row_widgets.append(header)
                if value.get("is_main", False):
                    self.sticky_main_widget = header
                elif value.get("base") == "A" and self.sticky_audio_widget is None:
                    self.sticky_audio_widget = header
            elif kind == "section":
                cell = QFrame(self)
                cell.setStyleSheet(
                    "QFrame{background:#10151C;border-top:1px solid #252D37;"
                    "border-bottom:1px solid #252D37;}"
                )
                layout = QHBoxLayout(cell)
                layout.setContentsMargins(8, 0, 4, 0)
                label = QLabel(str(value), cell)
                label.setStyleSheet(
                    "color:#7C8997;font-size:8px;font-weight:800;border:0;"
                )
                layout.addWidget(label)
                layout.addStretch()
                cell.setGeometry(0, y, width, height)
                cell.show()
                self._row_widgets.append(cell)
            else:
                cell = QFrame(self)
                cell.setStyleSheet("QFrame{background:#212123;border:0;}")
                cell.setGeometry(0, y, width, height)
                cell.show()
                self._row_widgets.append(cell)

        # Keep the left layer controls aligned with the timeline's dedicated
        # bottom drop target, including the extra scrollable workspace.
        add_zone = QFrame(self)
        add_zone.setAcceptDrops(False)
        add_zone.setStyleSheet(
            "QFrame{background:#1B1D20;border-top:1px solid #30343A;border-bottom:1px solid #25282D;}"
        )
        add_layout = QVBoxLayout(add_zone)
        add_layout.setContentsMargins(6, 4, 6, 4)
        add_label = QLabel("+  Add layer")
        add_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add_label.setStyleSheet("color:#8D98A5;font-size:9px;border:0;")
        add_layout.addWidget(add_label)
        zone_height = int(self.timeline.bottom_new_layer_height())
        add_zone.setGeometry(
            0,
            max(0, int(self.timeline.layer_content_height()) - zone_height),
            width,
            zone_height,
        )
        visible_track_rows = sum(1 for row in row_geometry if row[0] == "track")
        add_zone.setVisible(visible_track_rows >= 5)
        self._row_widgets.append(add_zone)

        # Main header is created in the same shared row loop as every track.
        self._position_sticky_main()
        self._position_sticky_audio()

    def _position_sticky_main(self):
        """Mirror the timeline: Main's label row is pinned identically."""
        widget = getattr(self, "sticky_main_widget", None)
        if widget is None:
            return
        try:
            from ..track_layout import main_row_display_y
            positions = main_row_display_y(self.timeline)
            if positions is None:
                return
            _natural, y = positions
            if widget.y() != y:
                widget.move(widget.x(), int(y))
            widget.raise_()
        except RuntimeError:
            pass

    def _position_sticky_audio(self):
        """Audio labels scroll naturally; Main alone is sticky."""
        return



# ============================================================
# Real multitrack project-preview engine
# ============================================================

