"""UI-only helpers for the Skyzen timeline panel.

Keep visual placeholder behavior here; timeline state and editing logic
remain owned by core.py.
"""
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel


class EmptyTimelineHint(QLabel):
    """A small hover-only hint shown when the project has no clips."""

    def __init__(self, timeline, viewport):
        super().__init__("Drop media to start editing", viewport)
        self.timeline = timeline
        self.viewport = viewport
        self.setObjectName("SkyzenEmptyTimelineHint")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(238, 34)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.setStyleSheet(
            "QLabel#SkyzenEmptyTimelineHint {"
            " color:#A1A1A6;"
            " background:rgba(25,29,35,205);"
            " border:1px solid #303945;"
            " border-radius:6px;"
            " padding:4px 10px;"
            " font-size:11px;"
            "}"
        )
        viewport.setMouseTracking(True)
        viewport.installEventFilter(self)
        content = getattr(timeline, "content", None)
        if content is not None:
            content.setMouseTracking(True)
            content.installEventFilter(self)
        self._hovered = False
        self.hide()
        self.reposition()
        self.refresh()

    def has_media(self):
        for track in getattr(self.timeline, "tracks", ()):
            if track.get("clips"):
                return True
        return False

    def refresh(self):
        """Update visibility from the project state and current hover."""
        should_show = self._hovered and not self.has_media()
        self.setVisible(bool(should_show))
        if should_show:
            self.reposition()
            self.raise_()

    def reposition(self):
        self.move(
            max(0, (self.viewport.width() - self.width()) // 2),
            max(0, (self.viewport.height() - self.height()) // 2),
        )

    def eventFilter(self, watched, event):
        if watched not in (
            self.viewport,
            getattr(self.timeline, "content", None),
        ):
            return False

        event_type = event.type()
        if event_type == QEvent.Type.Enter:
            self._hovered = True
            self.refresh()
        elif event_type == QEvent.Type.Leave:
            # Qt may transition between viewport and its content widget.
            # Defer the final hover check so crossing that boundary doesn't
            # cause a persistent flicker.
            QTimer.singleShot(0, self._refresh_hover_state)
        elif event_type == QEvent.Type.Resize:
            self.reposition()
        return False

    def _refresh_hover_state(self):
        # The hint ignores mouse input; checking the global cursor position
        # against the viewport keeps the hint hover-only without blocking
        # drag/drop or clip interactions.
        try:
            inside = self.viewport.rect().contains(
                self.viewport.mapFromGlobal(QCursor.pos())
            )
        except Exception:
            inside = False
        self._hovered = inside
        self.refresh()


def create_empty_timeline_hint(timeline, viewport):
    """Create the placeholder without adding layout constraints."""
    return EmptyTimelineHint(timeline, viewport)


def build_empty_toolbar(timeline):
    """Build the small, functional basic-edit toolbar.

    Keep the legacy hidden widget attributes because core.py still references
    them, but expose only features that work in the current basic-editor stage.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QFrame, QHBoxLayout, QLabel, QSlider, QToolButton, QWidget, QSizePolicy
    )

    bar = QFrame()
    bar.setObjectName("SkyzenTimelineToolbar")
    bar.setFixedHeight(30)
    bar.setStyleSheet(
        "QFrame#SkyzenTimelineToolbar { background:#212123; border-bottom:1px solid #2A2E34; }"
        "QToolButton { color:#E8EDF5; background:transparent; border:1px solid transparent;"
        " border-radius:4px; padding:3px 6px; min-height:21px; }"
        "QToolButton:hover { background:#303238; border-color:#3D4652; }"
        "QToolButton:pressed { background:#0B3038; border-color:#00D9FF; }"
        "QLabel { color:#A1A1A6; padding:0 4px; }"
    )
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(6, 1, 6, 1)
    layout.setSpacing(2)

    timeline._toolbar_buttons = {}

    # Compatibility attributes referenced by the current timeline core.
    for name in (
        "_razor_button", "_transform_button", "_pan_button",
        "_trim_follow_button", "_axis_button", "_magnetic_button",
        "snap_button", "effects_view_button", "render_button",
    ):
        button = QToolButton(bar)
        button.setCheckable(True)
        button.hide()
        setattr(timeline, name, button)

    def add_action(key, label, tooltip, callback):
        button = QToolButton(bar)
        button.setText(label)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)
        timeline._toolbar_buttons[key] = button
        return button

    add_action("undo", "↶", "Undo (Ctrl+Z)", timeline.undo)
    add_action("redo", "↷", "Redo (Ctrl+Y)", timeline.redo)

    divider = QFrame(bar)
    divider.setFixedWidth(1)
    divider.setStyleSheet("background:#363B43;")
    layout.addWidget(divider)

    def focus_crop():
        clip = getattr(timeline, "selected_clip", None)
        if not isinstance(clip, dict):
            return
        if str(clip.get("kind", "Video")).strip().lower() not in ("video", "image"):
            return
        try:
            from .crop_dialog import CropDialog
            dialog = CropDialog(timeline, timeline.window())
            dialog.exec()
        except (AttributeError, RuntimeError, ImportError):
            pass

    crop_button = add_action("crop", "[ ]", "Crop the selected video or image", focus_crop)
    crop_button.setObjectName("TimelineCropButton")
    add_action("frame_peek", "Frame Peek", "Toggle the independent frame-preview marker", timeline._concat_toggle_preview_axis)
    add_action("split", "]|[", "Split selected clip at the playhead", timeline.split_selected)
    add_action("delete", "⌫ Delete", "Delete selected clip", timeline.delete_selected)
    add_action("trim_left", "]", "Trim the selected clip start to the playhead", timeline.trim_selected_left)
    add_action("trim_right", "[", "Trim the selected clip end from the playhead", timeline.trim_selected_right)

    # Selection-aware toolbar: object operations are visibly inactive until a clip is selected.
    from PySide6.QtCore import QTimer
    object_action_keys = ("crop", "split", "delete", "trim_left", "trim_right")
    for key in object_action_keys:
        timeline._toolbar_buttons[key].setEnabled(False)

    def refresh_object_actions():
        try:
            selected = getattr(timeline, "selected_clip", None)
            if callable(selected):
                selected = selected()
            if selected is None:
                selected = getattr(timeline, "_selected_clip", None)
            has_selection = selected is not None
            for key in object_action_keys:
                button = timeline._toolbar_buttons.get(key)
                if button is not None:
                    button.setEnabled(has_selection)
        except (RuntimeError, AttributeError):
            pass

    timeline._toolbar_selection_timer = QTimer(bar)
    timeline._toolbar_selection_timer.setInterval(150)
    timeline._toolbar_selection_timer.timeout.connect(refresh_object_actions)
    timeline._toolbar_selection_timer.start()
    refresh_object_actions()

    layout.addStretch(1)
    layout.addWidget(QLabel("Zoom"))

    timeline.zoom_slider = QSlider(Qt.Orientation.Horizontal, bar)
    timeline.zoom_slider.setObjectName("TimelineZoomSlider")
    timeline.zoom_slider.setRange(
        int(getattr(timeline, "ZOOM_MIN_VALUE", 0)),
        int(getattr(timeline, "ZOOM_MAX_VALUE", 10000)),
    )
    timeline.zoom_slider.setValue(
        int(getattr(timeline, "ZOOM_CENTER_VALUE", 5000))
    )
    timeline.zoom_slider.setFixedWidth(112)
    timeline.zoom_slider.setToolTip("Timeline zoom")
    timeline.zoom_slider.valueChanged.connect(timeline.set_zoom)
    layout.addWidget(timeline.zoom_slider)

    timeline.zoom_label = QLabel("30s", bar)
    timeline.zoom_label.setMinimumWidth(36)
    timeline.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(timeline.zoom_label)

    return bar
