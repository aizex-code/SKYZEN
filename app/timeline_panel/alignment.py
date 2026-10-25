"""Vertical scroll synchronisation for the Skyzen timeline.

CapCut-style structure: the track canvas (``tracks_scroll``) is the ONLY real
vertical scroller.  The layer-label column and the edit gutter are plain
clipping widgets whose content is moved to ``y = -scroll_value``.  Because they
do not own a scrollbar there is no range to mismatch, nothing to clamp, and the
label rows are level with the clip rows by construction.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QWidget

from .track_layout import wheel_scroll_delta


class SyncedColumn(QWidget):
    """Clipping viewport whose single child is offset by the master scroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content = None
        self._offset = 0

    # QScrollArea-compatible surface used by the rest of the code base.
    def setWidget(self, widget):
        self._content = widget
        widget.setParent(self)
        widget.move(0, -self._offset)
        widget.show()

    def widget(self):
        return self._content

    def viewport(self):
        return self

    def set_offset(self, y: int):
        self._offset = max(0, int(y))
        if self._content is not None:
            self._content.move(0, -self._offset)


class TimelineScrollCoordinator(QObject):
    """Keep label/gutter columns locked to the tracks scroll position."""

    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self._master = timeline.tracks_scroll
        self._columns = tuple(
            c for c in (timeline.sidebar_scroll, timeline.edit_gutter_scroll)
            if c is not None
        )

        bar = self._master.verticalScrollBar()
        bar.setSingleStep(timeline.TRACK_HEIGHT)
        bar.setPageStep(timeline.TRACK_HEIGHT * 4)
        bar.valueChanged.connect(self._apply_offset)
        bar.rangeChanged.connect(lambda *_: self._apply_offset())

        # One wheel policy for tracks and label columns.
        self._master.viewport().installEventFilter(self)
        for column in self._columns:
            column.installEventFilter(self)
        self._apply_offset()

    # ------------------------------------------------------------------
    def _apply_offset(self, *_args):
        value = int(self._master.verticalScrollBar().value())
        for column in self._columns:
            try:
                column.set_offset(value)
            except RuntimeError:
                pass
        try:
            self.timeline._position_sticky_main_rows()
        except (AttributeError, RuntimeError):
            pass

    def align_ranges(self):
        """Re-apply the offset after content/geometry changes."""
        t = self.timeline
        try:
            height = max(1, int(t.layer_content_height()))
            if int(t.content.height()) != height:
                t.content.setFixedHeight(height)
            for widget in (t.sidebar_content, t.edit_gutter_content):
                if int(widget.height()) != height:
                    widget.setFixedHeight(height)
        except RuntimeError:
            return
        self._apply_offset()

    def sync_from_value(self, value):
        bar = self._master.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), int(value))))
        self._apply_offset()

    # ------------------------------------------------------------------
    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Resize and watched is self._master.viewport():
            # Viewport height changes the bottom-anchored pad above the stack.
            QTimer.singleShot(0, self._reanchor)
            return False
        if kind != QEvent.Type.Wheel:
            return False
        try:
            mods = event.modifiers()
            if mods & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
            ):
                return bool(self.timeline._scroll_timeline_wheel(event))
            delta = wheel_scroll_delta(
                int(event.angleDelta().y()),
                int(event.pixelDelta().y()),
                int(self.timeline.TRACK_HEIGHT),
            )
            if not delta:
                return False
            bar = self._master.verticalScrollBar()
            bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() + delta)))
            event.accept()
            return True
        except RuntimeError:
            return False

    def _reanchor(self):
        try:
            self.timeline.reanchor_if_needed()
        except (AttributeError, RuntimeError):
            pass
