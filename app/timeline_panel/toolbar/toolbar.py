"""Timeline toolbar actions; preserve core editing tools and add keyframe curves."""
from PySide6.QtWidgets import QInputDialog, QPushButton, QMessageBox
from app.animation import normalize_keyframes
from app.curve_editor import CurveEditorDialog
from app.timeline_panel.ui import build_empty_toolbar


def _edit_selected_curve(timeline):
    """Edit easing for the keyframe segment under the playhead, not key values."""
    clip = getattr(timeline, "selected_clip", None)
    if not isinstance(clip, dict):
        QMessageBox.information(timeline, "Keyframe curve", "Select a clip first.")
        return

    keyframes = clip.get("keyframes", {}) or {}
    candidates = [name for name, raw in keyframes.items()
                  if len(normalize_keyframes(raw)) >= 2]
    if not candidates:
        QMessageBox.information(
            timeline, "Keyframe curve",
            "Add at least two keyframes to one property using the ◇ buttons in the Inspector."
        )
        return
    if len(candidates) == 1:
        prop = candidates[0]
    else:
        prop, ok = QInputDialog.getItem(
            timeline, "Keyframe curve", "Choose animated property", candidates, 0, False
        )
        if not ok:
            return

    points = normalize_keyframes(keyframes[prop])
    duration = max(float(clip.get("duration", 1.0)), 1.0 / max(1, int(timeline.FPS)))
    local_t = max(0.0, min(duration, float(timeline.playhead) - float(clip.get("start", 0.0))))
    segment = 0
    for i, (left, right) in enumerate(zip(points, points[1:])):
        if left["time"] <= local_t <= right["time"]:
            segment = i
            break
        if local_t > right["time"]:
            segment = min(i + 1, len(points) - 2)
    left = points[segment]
    ease = left.get("ease", "linear")
    canvas_points = CurveEditorDialog.points_for_ease(ease)
    dialog = CurveEditorDialog(
        f"Keyframe easing · {prop} · {left['time']:.2f}s–{points[segment+1]['time']:.2f}s",
        canvas_points, "ease", timeline
    )
    if not dialog.exec():
        return
    updated_ease = dialog.easing()
    try:
        timeline._push_history()
    except (AttributeError, TypeError):
        pass
    # Store the easing on the left keyframe; it controls the segment to its right.
    left["ease"] = updated_ease
    clip["keyframes"][prop] = points
    timeline._emit_active_clips(timeline.playhead)
    try:
        timeline.time_changed.emit(timeline.playhead)
    except (AttributeError, RuntimeError):
        pass


def build_toolbar(timeline):
    """Reuse the full, proven edit toolbar and append the curve action."""
    bar = build_empty_toolbar(timeline)
    bar.setObjectName("SkyzenTimelineToolbar")
    layout = bar.layout()
    curve = QPushButton("◇ Curve", bar)
    curve.setObjectName("TimelineKeyframeCurveButton")
    curve.setToolTip("Edit easing between keyframes on the selected clip")
    curve.setStyleSheet(
        "QPushButton{background:#292D33;color:#BFC8D2;border:1px solid #373E47;"
        "border-radius:4px;padding:3px 8px;font-size:10px;}"
        "QPushButton:hover{background:#343B43;color:#FFFFFF;border-color:#00CFE3;}"
    )
    curve.clicked.connect(lambda: _edit_selected_curve(timeline))
    # Keep curve tools next to split/delete/trim while preserving zoom controls.
    anchor = timeline._toolbar_buttons.get("trim_right")
    index = layout.indexOf(anchor) + 1 if anchor is not None else max(0, layout.count() - 4)
    layout.insertWidget(index, curve)
    timeline._keyframe_curve_button = curve
    return bar
